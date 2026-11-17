# Entry points for the advertising source-OLTP project.
# `make` lists the targets. Override the variables below on the command line, e.g.
#   make backfill PROFILE=medium WORKERS=4 DQ="late_events=0.02 orphan_refs=0.005"
#   make run SPEED=60 DURATION=10m
#   make psql DB=media_ops_db
#   make stats DOCKER=1                 (simulator targets inside the advsim container)
#   make sim-up PROFILE=tiny SPEED=60   (containerised backfill-then-stream)

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Simulator profile: tiny | small | medium | large (config/advsim/profiles/)
PROFILE ?= small
# Backfill window and reproducibility; empty means the profile default
START ?=
END ?= now
SEED ?=
WORKERS ?= 1
# 1 truncates every source table before a backfill; 0 appends
RESET ?= 1
# Data-quality noise, space-separated KEY=VALUE pairs (config/advsim/dq.yaml)
DQ ?=
# Live run: activity multiplier and stop time (90s, 30m, 2h; empty runs until Ctrl-C)
SPEED ?= 1
DURATION ?=
# Allowed share of dangling soft references for `make validate`
ORPHAN_TOLERANCE ?= 0.0
# Target database(s) for `make psql` (one) and `make reset` (empty means all)
DB ?=
# 1 runs the simulator targets (backfill ... stats) in the advsim container instead of on the host
DOCKER ?= 0

DBS := crm_db erp_db media_ops_db work_mgmt_db adserver_db cdp_db
SVC_crm_db := pg-crm
SVC_erp_db := pg-erp
SVC_media_ops_db := pg-media-ops
SVC_work_mgmt_db := pg-work-mgmt
SVC_adserver_db := pg-adserver
SVC_cdp_db := pg-cdp

# Compose commands that must also see the opt-in advsim service
COMPOSE_ALL := docker compose --profile sim
ifeq ($(DOCKER),1)
ADVSIM := docker compose run --rm --build advsim
else
ADVSIM := uv run advsim
endif
opt = $(if $(2),$(1) $(2))
SIM_ARGS = --profile $(PROFILE) $(call opt,--seed,$(SEED)) $(foreach d,$(DQ),--dq $(d))
BACKFILL_ARGS = $(SIM_ARGS) --end $(END) --workers $(WORKERS) $(call opt,--start,$(START)) \
	$(if $(filter 1,$(RESET)),--reset)
SERVE_ARGS = $(SIM_ARGS) --speed $(SPEED) --workers $(WORKERS)

.PHONY: help install build test test-pg lint up down recreate status deploy psql \
	backfill dry-run run reset validate stats demo destroy clean \
	sim-build sim-up sim-down sim-logs sim-shell

help: ## List targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo
	@echo "Variables: PROFILE=$(PROFILE) START=$(START) END=$(END) SEED=$(SEED) WORKERS=$(WORKERS) RESET=$(RESET)"
	@echo "           DQ=$(DQ) SPEED=$(SPEED) DURATION=$(DURATION) ORPHAN_TOLERANCE=$(ORPHAN_TOLERANCE) DB=$(DB)"
	@echo "           DOCKER=$(DOCKER)"

# --- workspace -------------------------------------------------------------

install: ## Install the uv workspace (advgen + advsim + dev tools)
	uv sync

build: ## Regenerate models/, dictionary/, mapping/ from source/ + overrides/
	uv run advgen build

test: ## Offline tests (model coverage + simulator)
	uv run pytest

test-pg: ## End-to-end simulator test against the databases (TRUNCATES them)
	uv run pytest -m pg

lint: ## Ruff lint of packages/ and tests/
	uvx ruff check packages tests

# --- databases -------------------------------------------------------------

up: ## Start the six PostgreSQL instances
	docker compose up -d --wait

down: ## Stop the instances and the simulator (data volumes are kept)
	$(COMPOSE_ALL) down

recreate: ## Recreate the containers, e.g. after changing docker-compose.yml (volumes kept)
	docker compose up -d --force-recreate --wait

status: ## Show the containers and their health
	$(COMPOSE_ALL) ps

deploy: sim-down ## Stop the simulator, drop and recreate all six databases from the DDL, verify them
	scripts/verify.sh --keep

psql: ## Open psql on one database: make psql DB=crm_db
	@$(if $(filter $(DB),$(DBS)),,echo "DB must be one of: $(DBS)" >&2; exit 2)
	docker compose exec $(SVC_$(DB)) psql -U postgres -d $(DB)

destroy: ## Stop everything and DELETE the data volumes
	$(COMPOSE_ALL) down -v

# --- simulator -------------------------------------------------------------

backfill: ## Generate and load history (truncates first unless RESET=0)
	$(ADVSIM) backfill $(BACKFILL_ARGS)

dry-run: ## Build the backfill world in memory without writing anything
	$(ADVSIM) backfill $(BACKFILL_ARGS) --dry-run

run: ## Live simulation until Ctrl-C or DURATION
	$(ADVSIM) run $(SIM_ARGS) --speed $(SPEED) $(call opt,--duration,$(DURATION))

reset: ## Truncate source tables (all, or DB="crm_db erp_db"); ref code sets are kept
	$(ADVSIM) reset $(foreach d,$(DB),--db $(d))

validate: ## Check cross-database references and business invariants
	$(ADVSIM) validate --orphan-tolerance $(ORPHAN_TOLERANCE)

stats: ## Row counts per database and table
	$(ADVSIM) stats

demo: PROFILE = tiny
demo: deploy backfill validate stats ## Deploy, backfill the tiny profile, validate and show counts

# --- simulator container -----------------------------------------------------

sim-build: ## Build the advsim image
	docker compose build advsim

sim-up: ## Start the advsim container: backfills PROFILE if a database is empty, then streams at SPEED
	ADVSIM_ARGS="$(SERVE_ARGS)" docker compose up -d --build advsim
	@echo "advsim started; follow it with: make sim-logs"

sim-down: ## Stop and remove the advsim container (databases keep running)
	docker compose rm -sf advsim

sim-logs: ## Follow the advsim container output
	docker compose logs -f advsim

sim-shell: ## Shell in a one-off advsim container (advsim CLI on PATH)
	docker compose run --rm --entrypoint bash advsim

# --- housekeeping ----------------------------------------------------------

clean: ## Remove Python, pytest and ruff caches
	rm -rf .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -not -path './.venv/*' -prune -exec rm -rf {} +
