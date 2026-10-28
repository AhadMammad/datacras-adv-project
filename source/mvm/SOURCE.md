# Pinned source: Advertising MVM (v1)

| Item | Value |
|---|---|
| Repository | https://github.com/databricks-industry-solutions/lakehouse-industry-data-models |
| Path | `data-models/advertising/v1/mvm` |
| Commit | `a50067f486b69e1e09603fa39ae5feac031cd702` |
| Retrieved | 2026-10-17 |

| File | Upstream path | Role |
|---|---|---|
| `advertising_model_v1_mvm.csv` | `docs/advertising_model_v1_mvm.csv` | **Canonical input** for the generator (one row per attribute) |
| `advertising_dbml_v1_mvm.txt` | `diagram/advertising_dbml_v1_mvm.txt` | Reference only (its FK column names differ from the CSV in places; the CSV wins) |
| `readme.md` | `readme.md` | Domain and product descriptions |
| `releasenotes.txt` | `docs/releasenotes.txt` | Upstream change history |

To re-pin, download the same files at a new commit, update this table, and run `uv run advgen build`.
