# Advertising source OLTP models

This repository holds the operational (OLTP) **source-system databases** that feed the Databricks
[Advertising lakehouse MVM](https://github.com/databricks-industry-solutions/lakehouse-industry-data-models/tree/main/data-models/advertising/v1/mvm).
It contains conceptual, logical and physical models for PostgreSQL 18.

The MVM is an analytical (Silver-layer) model with 10 domains, 95 tables and 3,760 attributes. This
project reverse-engineers the systems of record that would produce it: six PostgreSQL databases,
each on its own instance and each modelled after the system a real agency runs.

| Database | Plays the role of | Instance | Tables | Columns | `ref` code sets | Enforced FKs* | Soft refs |
|---|---|---|---|---|---|---|---|
| `crm_db` | Salesforce Sales Cloud (CRM) | `pg-crm` :5433 | 17 | 687 | 29 | 92 | 36 |
| `erp_db` | SAP S/4HANA (FI/CO, AP/AR) | `pg-erp` :5434 | 14 | 627 | 14 | 53 | 120 |
| `media_ops_db` | Mediaocean Prisma (media planning and buying) | `pg-media-ops` :5435 | 27 | 1089 | 39 | 172 | 95 |
| `work_mgmt_db` | Adobe Workfront + DAM | `pg-work-mgmt` :5436 | 19 | 756 | 19 | 105 | 95 |
| `adserver_db` | Google CM360 / The Trade Desk | `pg-adserver` :5437 | 9 | 425 | 6 | 11 | 112 |
| `cdp_db` | Customer Data Platform / DMP | `pg-cdp` :5438 | 9 | 349 | 6 | 26 | 41 |

\* Includes FKs to `ref.*` lookup tables.

## Where to start

| You want… | Read |
|---|---|
| The business picture: systems, concepts and relationships | [models/conceptual/conceptual_model.md](models/conceptual/conceptual_model.md) |
| The same picture as diagrams (open in a browser) | [models/conceptual/business_model_explained.html](models/conceptual/business_model_explained.html) |
| Entities, attributes, optionality and relationships per system | [models/logical/](models/logical/) |
| Tables, keys and physical ERDs | `models/physical/<db>/erd.md` and `<db>.dbml` (import into [dbdiagram.io](https://dbdiagram.io)) |
| Deployable DDL | `models/physical/<db>/ddl/*.sql` |
| Every column: type, constraints, description and lineage | [dictionary/](dictionary/) (`data_dictionary.csv` and one Markdown file per database) |
| MVM → OLTP lineage | [mapping/mvm_to_oltp_mapping.csv](mapping/mvm_to_oltp_mapping.csv) |
| Unenforced cross-system references | [mapping/cross_system_refs.csv](mapping/cross_system_refs.csv) |
| Why the models differ from the MVM | [mapping/decision_log.md](mapping/decision_log.md) |

## Conventions (summary)

The full rationale is in the [decision log](mapping/decision_log.md).

- **Keys:** every table has `<table>_id uuid DEFAULT uuidv7()`. All MVM `BIGINT` keys become `uuid`.
- **References:** inside one database, references are enforced FKs (`ON DELETE RESTRICT`). Across
  databases, or to a partitioned table, they are **soft references**: an indexed `uuid` column with
  no constraint, documented in the column comment and in `cross_system_refs.csv`.
- **Code sets:** the MVM's 140 `ENUM-REF-CANDIDATE` columns reference 113 lookup tables in schema
  `ref`. Each has `code`, `label`, `sort_order` and `is_active`, and is seeded from the MVM values.
  The other MVM value lists are `CHECK (col IN (…))`.
- **Strictness:** inferred NOT NULL, regex and range CHECKs, `end >= start` date pairs, and unique
  business keys.
- **Audit:** `created_at`, `created_by`, `updated_at` and `updated_by` on every table, maintained by
  `audit.set_updated()`. Applications identify the acting user with `SET app.actor = '<user>'`.
- **Events:** the six high-volume `adserver_db` tables are range-partitioned by month, with BRIN
  indexes. Run `util.ensure_monthly_partitions()` on a schedule to keep partitions ahead of incoming
  data.
- **Schemas:** each MVM domain is a schema inside the database that owns it (for example,
  `crm_db.client`).

## Deploy and verify

Requirements: Docker, [uv](https://docs.astral.sh/uv/), and Node.js (only for diagram and DBML
validation).

```bash
uv sync                    # install the workspace (advgen + advsim)
uv run advgen build        # regenerate every artifact from source/ + overrides/
uv run pytest              # model coverage tests + simulator offline tests
scripts/verify.sh          # 6 PostgreSQL 18 instances: deploy DDL, check counts, CDC, smoke test
```

`verify.sh` recreates each database and applies `ddl/000`–`095` in order with `ON_ERROR_STOP`. It
then compares the object counts with `models/physical/manifest.json` and runs `tests/smoke/<db>.sql`.
The smoke test inserts one valid row into every table and checks the audit trigger, rejection of
FK and CHECK violations, and monthly partition routing; it rolls everything back. It also checks that
each database has its CDC publication (`<db>_cdc`, `ddl/095`) and runs with `wal_level=logical`.
Pass `--keep` to leave the containers running. If the containers were created before
`wal_level=logical` was added to `docker-compose.yml`, recreate them once with
`docker compose up -d --force-recreate` (the volumes are kept).

To deploy one database to an existing server by hand:

```bash
psql -d postgres -f models/physical/crm_db/ddl/000_database.sql
for f in models/physical/crm_db/ddl/0[1-9]*.sql; do psql -v ON_ERROR_STOP=1 -d crm_db -f "$f"; done
```

Optional checks on the docs:

```bash
npx -p @dbml/cli dbml2sql --postgres models/physical/crm_db/crm_db.dbml   # DBML parses
npx -p @mermaid-js/mermaid-cli mmdc -i models/logical/crm_db.md -o /tmp/out.md   # ERDs render
```

## Simulating data

`advsim` fills the six databases with fake but realistic, mutually consistent data: an agency with
its staff, cost centers and chart of accounts; clients with brands, contracts, SOWs and rate cards;
publishers and tech partners; audiences; and, month by month, campaigns that flow from brief to
plan, IOs, flights, line items, creative production, ad delivery, client billing, vendor invoices,
payables, payments and reconciliation. Cross-database references (for example
`media_ops_db.campaign.advertiser_id` -> `crm_db.client.advertiser`) always point at rows that exist.

```bash
scripts/verify.sh --keep                                   # databases up, DDL deployed
uv run advsim backfill --profile small --reset             # history from 2026-01-01 until now
uv run advsim validate                                     # soft refs resolve, business invariants hold
uv run advsim stats                                        # row counts per database/table
uv run advsim run --profile small --speed 60               # live activity until Ctrl-C (or --duration 2h)
```

**Backfill** builds the world in memory, loads it in foreign-key order with `COPY`, and then writes
ad-server events day by day. Pass `--seed` for reproducible output, `--start`/`--end` for another
window, `--workers N` to load events in parallel processes, and `--dry-run` to build without
writing anything.

**Run** reloads the current state from the databases and then, every second, inserts impressions,
clicks, video and conversion events for live line items. It moves statuses along their lifecycles
(UPDATEs), creates new advertisers, suppliers and campaigns, invoices the previous month, and
deletes rows that real systems delete (draft time entries, expired segment members and similar).
`--speed N` makes N times as much happen per second. **Timestamps are always wall-clock**, so
`created_at`/`updated_at` (set by the audit trigger) stay consistent with what CDC sees.

**Event sampling.** Budgets, spend, pacing and invoices are realistic (millions of dollars), so
storing every impression would mean billions of rows. Each stored event row stands for
`delivery.sample_rate` real events (small: 2,000; medium: 200; large: 1,000). `delivery_pacing`
and `viewability_measurement` carry the real totals, so the event count multiplied by the sample
rate approximately equals the pacing totals.

Measured for 2026-01-01 to 2026-10-28 with the default seed (`large` was not measured):

| Profile | Advertisers | Business rows | Stored event rows |
|---|---|---|---|
| `tiny` | 6 | ~8k | ~30k (tests and demos) |
| `small` | 30 | ~64k | ~2.3M |
| `medium` | 200 | ~475k | ~180M (use `--workers 4`) |
| `large` | 1,000 | ~2.4M (extrapolated) | ~200M (extrapolated; use `--workers 8`) |

**Data-quality noise** is off by default. Turn it on per run (`--dq late_events=0.02 --dq
duplicate_events=0.01 --dq orphan_refs=0.005`) or in a profile; see
[config/advsim/dq.yaml](config/advsim/dq.yaml). Validate a noisy run with
`advsim validate --orphan-tolerance 0.01`.

| File | Controls |
|---|---|
| `config/advsim/profiles/*.yaml` | Volumes, prices (CPM, CTR, CVR), pacing, payment lags, stream rates; `base.yaml` holds the defaults |
| `config/advsim/lifecycles.yaml` | Status state machines: status per date phase (backfill) and transitions and dwell times (stream) |
| `config/advsim/column_rules.yaml` | Per-column overrides for the generic filler (fill rate, fixed values, weighted choices) |
| `config/advsim/dq.yaml` | Data-quality noise rates |

How it works: [packages/advsim](packages/advsim) reads the same intermediate model as `advgen`
(columns, types, CHECKs, code sets, references), so every column of all 95 tables gets a valid
value. A generic filler derives values from column names and constraints, and keeps references
coherent through a row context: a campaign's line items, ads, invoices and events all point at the
same advertiser, brand and campaign. Hand-written scenarios in `src/advsim/scenarios/` set the
values that carry business meaning (keys, names, money, dates, statuses). `uv run pytest -m pg`
runs the end-to-end test against the databases; it **truncates** them.

## Changing the model

Everything under `models/`, `dictionary/` and `mapping/` (apart from the conceptual model and
`decision_log.header.md`) is **generated**. Change the inputs instead, then run `uv run advgen build`:

| File | Controls |
|---|---|
| `overrides/system_mapping.yaml` | Which database owns each MVM domain or subdomain, and the instance ports |
| `overrides/table_rules.yaml` | Business keys (UNIQUE), identifying attributes and the lifecycle status per table |
| `overrides/nullability.yaml` | NOT NULL inference patterns and forced exceptions |
| `overrides/conventions.yaml` | Audit-column mapping, partitioning, range checks, description cleanup |
| `overrides/code_sets.yaml` | Lookup labels and extra code values |
| `overrides/defect_fixes.yaml` | Added columns and corrected MVM descriptions |
| `overrides/type_overrides.yaml` | Explicit PostgreSQL types |

The generator lives in [packages/advgen](packages/advgen/src/advgen): `build.py` builds the intermediate model
and the `emit_*.py` modules write the artifacts. The source MVM is pinned in [source/mvm](source/mvm/SOURCE.md).

## Repository layout

```
packages/advgen/     model generator (MVM + overrides -> DDL, docs, dictionary, mapping)
packages/advsim/     data simulator (backfill + continuous), uses advgen's model
config/advsim/       simulator profiles, lifecycles, column rules, data-quality noise
overrides/           model generator inputs
models/ dictionary/ mapping/   generated model artifacts
source/mvm/          pinned Databricks Advertising MVM
scripts/verify.sh    deploy + verify all six databases
```
