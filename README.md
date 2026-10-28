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
uv sync                    # install the generator
uv run advgen build        # regenerate every artifact from source/ + overrides/
uv run pytest              # coverage tests (all MVM attributes, relationships, enums mapped)
scripts/verify.sh          # 6 PostgreSQL 18 instances: deploy DDL, check counts, smoke test
```

`verify.sh` recreates each database and applies `ddl/000`–`095` in order with `ON_ERROR_STOP`. It
then compares the object counts with `models/physical/manifest.json` and runs `tests/smoke/<db>.sql`.
The smoke test inserts one valid row into every table and checks the audit trigger, rejection of
FK and CHECK violations, and monthly partition routing; it rolls everything back. Pass `--keep` to
leave the containers running.

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

The generator lives in [generator/advgen](generator/advgen): `build.py` builds the intermediate model
and the `emit_*.py` modules write the artifacts. The source MVM is pinned in [source/mvm](source/mvm/SOURCE.md).
