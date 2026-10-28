# Decision log: Advertising MVM → PostgreSQL source OLTP models

This log records every decision that makes the OLTP models differ from the pinned MVM
(`source/mvm`, commit `a50067f`). The first part is maintained by hand; the sections
marked *Generated* are rebuilt by `uv run advgen build` from the overrides and the build.
Do not edit `decision_log.md` directly; edit `decision_log.header.md` or the files in `overrides/`.

## Scope decisions (agreed with the data owner, 2026-10-17)

| # | Topic | Decision | Consequence |
|---|---|---|---|
| D1 | Target DBMS | PostgreSQL, latest stable (18.x) | Native `uuidv7()`, builtin `C.UTF-8` locale, `timestamptz`, `numeric`. |
| D2 | OLTP shape | Six source-system databases, each on its own PostgreSQL instance | `crm_db`, `erp_db`, `media_ops_db`, `work_mgmt_db`, `adserver_db`, `cdp_db` (see `overrides/system_mapping.yaml`). |
| D3 | Scope | All 95 MVM tables with all 3,760 attributes | The lakehouse attribute depth is preserved for lineage, including denormalised columns. |
| D4 | Enumerations | `[ENUM-REF-CANDIDATE]` columns become lookup tables, one per code set | 113 `ref.*` tables with FKs (`ON UPDATE CASCADE`). Other MVM value lists become `CHECK (… IN …)`. |
| D5 | Raw events | Kept in the OLTP, range-partitioned monthly with BRIN indexes | Impression, click, video completion, viewability, conversion and pacing tables in `adserver_db`. |
| D6 | Cross-system references | Soft references: the `*_id uuid` column is kept and indexed, with no FK constraint | Listed in `cross_system_refs.csv` and in column comments (`LOGICAL REF -> …`). |
| D7 | Tenancy | Single agency | No tenant column or row-level security. |
| D8 | MVM defects | Fixed and documented | See *Defect fixes* below. |
| D9 | Primary keys | `uuid DEFAULT uuidv7()` | Every MVM `BIGINT` key and reference becomes `uuid`; ids are globally unique across the six systems, which makes soft references safe to resolve downstream. |
| D10 | Strictness | Strict | NOT NULL is inferred (see below), `value_regex` → CHECK, ranges on amounts and percentages, `end >= start` on date pairs, unique business keys. |
| D11 | Audit | `created_at`, `created_by`, `updated_at`, `updated_by` maintained by a shared trigger | MVM audit columns are renamed onto the standard set; tables lacking them get them added. |

## Design rules

**System assignment.** A table goes to the system named by the *system of record* that its MVM
column descriptions cite most (Salesforce → `crm_db`, SAP → `erp_db`, Prisma → `media_ops_db`,
Workfront/DAM → `work_mgmt_db`, CM360/TTD → `adserver_db`, CDP → `cdp_db`). The vendor domain is
split by subdomain: `vendor_registry` (supplier master, publishers, tech partners, rate cards) lives
with media buying, while `billing_reconciliation` (vendor invoices, IO lines, reconciliation,
evaluations) lives in the ERP.

**References.** An MVM foreign key becomes an enforced FK only when both tables are in the same
database *and* the target is not partitioned (PostgreSQL requires the partition key in any FK to a
partitioned table). All other references are soft. Self-references are always nullable.

**Type mapping.**

| MVM type | PostgreSQL type |
|---|---|
| BIGINT key/reference | `uuid` |
| BIGINT (measure) | `bigint` |
| INT | `integer` |
| DECIMAL(p,s) | `numeric(p,s)` |
| STRING with value_regex `^[A-Z]{3}$` | `char(3)` |
| STRING | `text` (no `varchar(n)`; lengths are enforced by CHECK where the MVM defines a pattern) |
| DATE | `date` |
| TIMESTAMP | `timestamptz` |
| BOOLEAN | `boolean` |

**NOT NULL inference**, applied in order (see `overrides/nullability.yaml`):

1. PK, audit columns and partition keys.
2. Business keys, identifying attributes and lifecycle status columns (`overrides/table_rules.yaml`).
3. Parent references: the MVM description says "Reference to the parent …" and the link is not an
   LLM-generated cross-domain link.
4. Booleans become `NOT NULL DEFAULT false`, unless the description admits unknown or null.
5. Descriptions that state "Nullable", "Null for …" or "populated only when …" undo rules 3 and 4.
6. Explicit overrides.

**Code-set scope.** One code set per (system, column name). Where several tables in one system
use the same column name with different candidate lists, the code set holds the union of the lists,
and each shared set is listed below. The `ref` tables carry `is_active`, so codes can be retired
without breaking existing rows.

**Descriptions.** MVM descriptions are kept verbatim in column comments, with two exceptions:
lakehouse-only phrasing ("in the Silver Layer") is removed, and enum and regex fragments are
replaced by the enforced constraint.

**Known limitations (accepted).**
- The MVM's attribute depth includes analytical, denormalised attributes (copied names, pre-computed
  rates such as CTR and ROAS). They are kept by D3 and flagged in the logical model as candidates for a
  stricter 3NF iteration.
- Soft references can dangle; the lakehouse conformance layer must handle unresolved ids.
- The NOT NULL rules are inferred from descriptions. Run the smoke test after changing them, and
  validate them against real source extracts before production.
