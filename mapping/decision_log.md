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

## Generated: transformation summary

| Metric | Value |
|---|---|
| MVM tables / columns | 95 / 3760 |
| OLTP tables / columns (excluding `ref`) | 95 / 3933 |
| Code sets (`ref.*` tables) | 113 |
| MVM relationships | 815 |
| → enforced FKs (same system) | 317 (plus added: `ad_format_id`, `parent_brand_id`) |
| → soft references | 498 (plus added: `contract_insertion_order_id`) |
| Columns NOT NULL | 993 |
| CHECK constraints | 1075 |
| Unique business keys | 52 |

## Generated: Defect fixes

| Target | Decision | Reason |
|---|---|---|
| `client.brand.parent_brand_id` | Added column (uuid). | The MVM describes brand_id as both the primary key and the parent-brand self-reference, so the brand hierarchy had no column of its own. |
| `media.placement.ad_format_id` | Added column (uuid). | Stub completion from product description |
| `media.placement.placement_code` | Added column (text). | Stub completion from product description |
| `media.placement.placement_name` | Added column (text). | Stub completion from product description |
| `media.placement.position_type` | Added column (text). | Stub completion from product description |
| `media.placement.fold_position` | Added column (text). | Stub completion from product description |
| `media.placement.viewability_rate_benchmark_pct` | Added column (numeric(5,2)). | Stub completion from product description |
| `media.placement.cpm_floor_price` | Added column (numeric(18,2)). | Stub completion from product description |
| `media.placement.floor_price_currency_code` | Added column (char(3)). | Stub completion from product description |
| `media.placement.estimated_monthly_reach` | Added column (bigint). | Stub completion from product description |
| `media.placement.cm360_placement_code` | Added column (text). | Stub completion from product description |
| `media.placement.ttd_inventory_code` | Added column (text). | Stub completion from product description |
| `media.placement.trafficking_requirements` | Added column (text). | Stub completion from product description |
| `media.placement.placement_status` | Added column (text). | Stub completion from product description |
| `media.media_insertion_order.contract_insertion_order_id` | Added column (uuid). | The MVM keeps two overlapping IO entities (media.media_insertion_order and contract.contract_insertion_order) with no link between them. Each stays in its own system, linked by this soft reference. |
| `client.brand.brand_id` | Description corrected to: Unique identifier for the brand. Primary key. Business name: Brand ID. | MVM (Parent Brand ID): Self-referencing identifier for the parent brand when this brand is a sub-brand or brand extension (e.g., Dove Men+Care is a sub-brand of Dove). Enables brand h |
| `audience.audience_activation` | FK descriptions naming `audience.audience_activation` rewritten to the actual target `audience.activation` (1 columns). | Stale table name in MVM description text; the CSV foreign_key_to is authoritative. |
| `audience.audience_segment` | FK descriptions naming `audience.audience_segment` rewritten to the actual target `audience.segment` (6 columns). | Stale table name in MVM description text; the CSV foreign_key_to is authoritative. |
| `audience.audience_taxonomy` | FK descriptions naming `audience.audience_taxonomy` rewritten to the actual target `audience.taxonomy` (3 columns). | Stale table name in MVM description text; the CSV foreign_key_to is authoritative. |
| `client.client_brand` | FK descriptions naming `client.client_brand` rewritten to the actual target `client.brand` (31 columns). | Stale table name in MVM description text; the CSV foreign_key_to is authoritative. |
| `contract.deliverable` | FK descriptions naming `contract.deliverable` rewritten to the actual target `contract.contract_deliverable` (1 columns). | Stale table name in MVM description text; the CSV foreign_key_to is authoritative. |
| `contract.insertion_order` | FK descriptions naming `contract.insertion_order` rewritten to the actual target `contract.contract_insertion_order` (5 columns). | Stale table name in MVM description text; the CSV foreign_key_to is authoritative. |
| `creative.creative_asset` | FK descriptions naming `creative.creative_asset` rewritten to the actual target `creative.asset` (6 columns). | Stale table name in MVM description text; the CSV foreign_key_to is authoritative. |
| `creative.creative_spec` | FK descriptions naming `creative.creative_spec` rewritten to the actual target `creative.spec` (3 columns). | Stale table name in MVM description text; the CSV foreign_key_to is authoritative. |
| `finance.budget` | FK descriptions naming `finance.budget` rewritten to the actual target `finance.finance_budget` (6 columns). | Stale table name in MVM description text; the CSV foreign_key_to is authoritative. |
| `media.media_buy` | FK descriptions naming `media.media_buy` rewritten to the actual target `media.buy` (1 columns). | Stale table name in MVM description text; the CSV foreign_key_to is authoritative. |
| `media.media_plan` | FK descriptions naming `media.media_plan` rewritten to the actual target `media.plan` (4 columns). | Stale table name in MVM description text; the CSV foreign_key_to is authoritative. |
| `media.media_plan_line` | FK descriptions naming `media.media_plan_line` rewritten to the actual target `media.plan_line` (2 columns). | Stale table name in MVM description text; the CSV foreign_key_to is authoritative. |
| `project.project_assignment` | FK descriptions naming `project.project_assignment` rewritten to the actual target `project.assignment` (1 columns). | Stale table name in MVM description text; the CSV foreign_key_to is authoritative. |
| `project.project_milestone` | FK descriptions naming `project.project_milestone` rewritten to the actual target `project.milestone` (8 columns). | Stale table name in MVM description text; the CSV foreign_key_to is authoritative. |
| `vendor.vendor_io_line` | FK descriptions naming `vendor.vendor_io_line` rewritten to the actual target `vendor.io_line` (3 columns). | Stale table name in MVM description text; the CSV foreign_key_to is authoritative. |

## Generated: Type overrides

| Target | Decision | Reason |
|---|---|---|
| `vendor.vendor_rate_card.source_system_rate_card_vendor_rate_card_id` | STRING -> uuid | Self-referencing FK typed STRING in the MVM (the only non-BIGINT key); all keys are uuid in the OLTP. |

## Generated: Partitioning

| Target | Decision | Reason |
|---|---|---|
| `performance.impression_event` | PARTITION BY RANGE (impression_timestamp), monthly; PK (impression_event_id, impression_timestamp). | High-volume raw event data; PostgreSQL requires the partition key in the PK. |
| `performance.click_event` | PARTITION BY RANGE (click_timestamp), monthly; PK (click_event_id, click_timestamp). | High-volume raw event data; PostgreSQL requires the partition key in the PK. |
| `performance.video_completion_event` | PARTITION BY RANGE (event_timestamp), monthly; PK (video_completion_event_id, event_timestamp). | High-volume raw event data; PostgreSQL requires the partition key in the PK. |
| `performance.viewability_measurement` | PARTITION BY RANGE (measurement_timestamp), monthly; PK (viewability_measurement_id, measurement_timestamp). | High-volume raw event data; PostgreSQL requires the partition key in the PK. |
| `performance.conversion_event` | PARTITION BY RANGE (conversion_timestamp), monthly; PK (conversion_event_id, conversion_timestamp). | High-volume raw event data; PostgreSQL requires the partition key in the PK. |
| `performance.delivery_pacing` | PARTITION BY RANGE (measurement_timestamp), monthly; PK (delivery_pacing_id, measurement_timestamp). | High-volume raw event data; PostgreSQL requires the partition key in the PK. |

## Generated: Same-system references not enforced

| Target | Decision | Reason |
|---|---|---|
| `performance.conversion_event.click_event_id` | Not enforced: target performance.click_event is partitioned. | An FK to a partitioned table must include its partition key, which the source row does not carry. |
| `performance.conversion_event.impression_event_id` | Not enforced: target performance.impression_event is partitioned. | An FK to a partitioned table must include its partition key, which the source row does not carry. |
| `performance.click_event.impression_event_id` | Not enforced: target performance.impression_event is partitioned. | An FK to a partitioned table must include its partition key, which the source row does not carry. |
| `performance.video_completion_event.impression_event_id` | Not enforced: target performance.impression_event is partitioned. | An FK to a partitioned table must include its partition key, which the source row does not carry. |
| `performance.viewability_measurement.impression_event_id` | Not enforced: target performance.impression_event is partitioned. | An FK to a partitioned table must include its partition key, which the source row does not carry. |

## Generated: Shared code sets (union of values)

| Target | Decision | Reason |
|---|---|---|
| `crm_db.ref.billing_frequency` | Shared by 2 columns; values are the union of their candidate lists (10 codes). | One code set per (system, column name). |
| `crm_db.ref.pricing_model` | Shared by 2 columns; values are the union of their candidate lists (19 codes). | One code set per (system, column name). |
| `crm_db.ref.unit_of_measure` | Shared by 2 columns; values are the union of their candidate lists (13 codes). | One code set per (system, column name). |
| `erp_db.ref.discrepancy_reason_code` | Shared by 2 columns; values are the union of their candidate lists (12 codes). | One code set per (system, column name). |
| `erp_db.ref.channel_type` | Shared by 2 columns; values are the union of their candidate lists (14 codes). | One code set per (system, column name). |
| `media_ops_db.ref.channel_type` | Shared by 4 columns; values are the union of their candidate lists (23 codes). | One code set per (system, column name). |
| `media_ops_db.ref.placement_type` | Shared by 2 columns; values are the union of their candidate lists (16 codes). | One code set per (system, column name). |
| `media_ops_db.ref.rate_type` | Shared by 2 columns; values are the union of their candidate lists (10 codes). | One code set per (system, column name). |
| `media_ops_db.ref.trafficking_status` | Shared by 4 columns; values are the union of their candidate lists (14 codes). | One code set per (system, column name). |
| `media_ops_db.ref.environment_type` | Shared by 2 columns; values are the union of their candidate lists (12 codes). | One code set per (system, column name). |
| `media_ops_db.ref.daypart` | Shared by 2 columns; values are the union of their candidate lists (12 codes). | One code set per (system, column name). |
| `media_ops_db.ref.deal_type` | Shared by 2 columns; values are the union of their candidate lists (8 codes). | One code set per (system, column name). |
| `media_ops_db.ref.platform_type` | Shared by 3 columns; values are the union of their candidate lists (25 codes). | One code set per (system, column name). |
| `media_ops_db.ref.pricing_model` | Shared by 2 columns; values are the union of their candidate lists (13 codes). | One code set per (system, column name). |
| `media_ops_db.ref.inventory_type` | Shared by 2 columns; values are the union of their candidate lists (15 codes). | One code set per (system, column name). |
| `work_mgmt_db.ref.file_format` | Shared by 3 columns; values are the union of their candidate lists (16 codes). | One code set per (system, column name). |
| `work_mgmt_db.ref.deliverable_status` | Shared by 2 columns; values are the union of their candidate lists (10 codes). | One code set per (system, column name). |
| `work_mgmt_db.ref.deliverable_type` | Shared by 3 columns; values are the union of their candidate lists (28 codes). | One code set per (system, column name). |
| `work_mgmt_db.ref.discipline` | Shared by 2 columns; values are the union of their candidate lists (13 codes). | One code set per (system, column name). |
| `adserver_db.ref.device_type` | Shared by 2 columns; values are the union of their candidate lists (11 codes). | One code set per (system, column name). |

## Generated: Parent references forced nullable

| Target | Decision | Reason |
|---|---|---|
| `campaign.budget_allocation.flight_id` | Forced nullable. | Allocations can be made at campaign level, before flights exist. |
| `campaign.budget_allocation.line_item_id` | Forced nullable. | Allocations can be made at campaign or flight level. |
| `campaign.trafficking_order.flight_id` | Forced nullable. | An order may be issued for the whole campaign rather than one flight. |
| `media.plan_line.media_placement_id` | Forced nullable. | Plan lines are created during planning, before a placement is bought. |
| `performance.tracking_pixel.media_placement_id` | Forced nullable. | Conversion pixels are advertiser-level tags, not tied to one placement. |
| `performance.delivery_pacing.media_placement_id` | Forced nullable. | Pacing is tracked per line item or per placement, not always both. |
| `finance.invoice_line.media_placement_id` | Forced nullable. | Invoice lines also bill fees and production, which have no placement. |

