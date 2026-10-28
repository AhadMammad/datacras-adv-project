"""Builds the OLTP IR from the pinned MVM sources and the override files."""
from __future__ import annotations

import csv
import os
import re
from collections import Counter, OrderedDict
from pathlib import Path

import yaml

from .model import Check, CodeSet, Column, Decision, Model, Ref, System, Table


def find_root() -> Path:
    """Repository root: $ADV_ROOT, else the nearest ancestor holding overrides/ and source/mvm."""
    if env := os.environ.get("ADV_ROOT"):
        return Path(env).resolve()
    for d in Path(__file__).resolve().parents:
        if (d / "overrides").is_dir() and (d / "source" / "mvm").is_dir():
            return d
    raise RuntimeError("repository root not found; set ADV_ROOT")


ROOT = find_root()
SOURCE = ROOT / "source" / "mvm"
OVERRIDES = ROOT / "overrides"
SOURCE_SHA = "a50067f486b69e1e09603fa39ae5feac031cd702"

LLM_LINK = "Internal - LLM Generated Cross-Domain Link"
ENUM_RE = re.compile(r"\[ENUM-REF-CANDIDATE:\s*(.*?)\s*(?:—.*?)?\]")
DECIMAL_RE = re.compile(r"DECIMAL\((\d+),(\d+)\)")
NUMERIC_TYPES = ("numeric", "integer", "bigint")


def load_yaml(name: str) -> dict:
    return yaml.safe_load((OVERRIDES / name).read_text()) or {}


def is_value_list(regex: str) -> bool:
    return bool(regex) and not regex.startswith("^") and "|" in regex


def map_type(row: dict) -> str:
    t = row["type"]
    if row["is_primary_key"] == "Y" or row["foreign_key_to"]:
        return "uuid"
    if t == "STRING":
        return "char(3)" if row["value_regex"] == "^[A-Z]{3}$" else "text"
    if m := DECIMAL_RE.fullmatch(t):
        return f"numeric({m.group(1)},{m.group(2)})"
    return {"BIGINT": "bigint", "INT": "integer", "BOOLEAN": "boolean",
            "DATE": "date", "TIMESTAMP": "timestamptz"}[t]


def parse_table_notes() -> dict[str, str]:
    """Table descriptions live only in the DBML (`Note: '...'` per table)."""
    text = (SOURCE / "advertising_dbml_v1_mvm.txt").read_text()
    notes = {}
    for m in re.finditer(r"^Table (\w+)\.(\w+) \{(.*?)^\}", text, re.S | re.M):
        n = re.search(r"^  Note: '((?:[^'\\]|\\.)*)'\s*$", m.group(3), re.M)
        notes[f"{m.group(1)}.{m.group(2)}"] = n.group(1).replace("\\'", "'") if n else ""
    return notes


class Builder:
    def __init__(self) -> None:
        self.rows = list(csv.DictReader((SOURCE / "advertising_model_v1_mvm.csv").open()))
        self.sysmap = load_yaml("system_mapping.yaml")
        self.conv = load_yaml("conventions.yaml")
        self.rules = load_yaml("table_rules.yaml")
        self.fixes = load_yaml("defect_fixes.yaml")
        self.types = load_yaml("type_overrides.yaml").get("overrides") or {}
        self.nulls = load_yaml("nullability.yaml")
        self.codes = load_yaml("code_sets.yaml")
        self.decisions: list[Decision] = []
        self.systems = {k: System(key=k, **v) for k, v in self.sysmap["systems"].items()}
        self.tables: dict[str, Table] = OrderedDict()
        part = self.conv["partitioning"]["tables"]
        self.partitioned = dict(part)

    def log(self, category: str, target: str, decision: str, reason: str = "") -> None:
        self.decisions.append(Decision(category, target, decision, reason))

    # ---------------------------------------------------------------- passes
    def build(self) -> Model:
        self.load_tables()
        self.apply_refs()
        self.apply_code_sets()
        self.apply_value_checks()
        self.apply_audit_columns()
        self.apply_defect_fixes()
        self.apply_type_overrides()
        self.apply_partitioning()
        self.apply_nullability()
        self.apply_table_rules()
        self.apply_ranges()
        self.apply_date_pairs()
        self.clean_descriptions()
        self.validate()
        return Model(self.systems, self.tables, self.decisions, self.rows, SOURCE_SHA)

    def resolve_system(self, domain: str, subdomain: str) -> str:
        for rule in self.sysmap["rules"]:
            if rule["domain"] == domain and rule.get("subdomain", subdomain) == subdomain:
                return rule["system"]
        raise ValueError(f"no system rule for {domain}/{subdomain}")

    def load_tables(self) -> None:
        notes = parse_table_notes()
        grouped: dict[tuple[str, str], list[dict]] = OrderedDict()
        for r in self.rows:
            grouped.setdefault((r["domain"], r["product"]), []).append(r)
        for (domain, product), rows in grouped.items():
            system = self.resolve_system(domain, rows[0]["subdomain"])
            t = Table(system=system, schema=domain, name=product, subdomain=rows[0]["subdomain"],
                      data_type=rows[0]["data_type"], description=notes.get(f"{domain}.{product}", ""))
            for r in rows:
                t.columns.append(Column(
                    name=r["column_name"], pg_type=map_type(r), description=r["description"],
                    is_pk=r["is_primary_key"] == "Y", glossary=r["business_glossary_term"],
                    tags=r["tags"], mvm=r))
            t.pk.default = "uuidv7()"
            t.pk.nullable = False
            t.pk.not_null_reason = "primary key"
            self.tables[t.key] = t
            self.systems[system].tables.append(t)

    def make_ref(self, source: Table, target_key: str, target_col: str | None = None) -> Ref:
        target = self.tables[target_key]
        same = target.system == source.system
        if not same:
            reason = "cross_system"
        elif target_key in self.partitioned:
            reason = "partitioned_target"
        else:
            reason = "same_system"
        return Ref(target.system, target.schema, target.name, target_col or target.pk.name,
                   enforced=reason == "same_system", reason=reason,
                   target_database=self.systems[target.system].database)

    def apply_refs(self) -> None:
        for t in self.tables.values():
            for c in t.columns:
                if fk := c.mvm["foreign_key_to"]:
                    d, p, col = fk.split(".")
                    c.ref = self.make_ref(t, f"{d}.{p}", col)
                    if c.mvm["type"] != "BIGINT":
                        c.notes.append(f"MVM type {c.mvm['type']} -> uuid (key column)")
                    else:
                        c.notes.append("BIGINT key -> uuid")
                elif c.is_pk:
                    c.notes.append("BIGINT key -> uuid DEFAULT uuidv7()")

    def apply_code_sets(self) -> None:
        for t in self.tables.values():
            system = self.systems[t.system]
            for c in t.columns:
                m = ENUM_RE.search(c.mvm["description"]) if c.mvm else None
                if not m:
                    continue
                values = [v.strip() for v in m.group(1).split("|") if v.strip()]
                if is_value_list(c.mvm["value_regex"]):
                    values += [v for v in c.mvm["value_regex"].split("|")]
                cs = system.code_sets.setdefault(c.name, CodeSet(system.key, c.name))
                for v in values:
                    if v not in cs.values:
                        cs.values.append(v)
                cs.usages.append((t.key, c.name))
                c.code_set = c.name
                c.notes.append(f"enum candidate -> FK to ref.{c.name}")
        for sys_key, extra in (self.codes.get("extra_values") or {}).items():
            for name, values in extra.items():
                self.systems[sys_key].code_sets[name].values.extend(values)
        acronyms = set(self.codes.get("label_acronyms") or [])
        for s in self.systems.values():
            for cs in s.code_sets.values():
                cs.labels = {v: label(v, acronyms) for v in cs.values}
                if len(cs.usages) > 1:
                    self.log("code_set", f"{s.database}.ref.{cs.name}",
                             f"Shared by {len(cs.usages)} columns; values are the union of their candidate lists ({len(cs.values)} codes).",
                             "One code set per (system, column name).")

    def apply_value_checks(self) -> None:
        for t in self.tables.values():
            for c in t.columns:
                rx = c.mvm["value_regex"] if c.mvm else ""
                if not rx or c.code_set:
                    continue
                if is_value_list(rx):
                    c.checks.append(Check("in", values=rx.split("|")))
                    c.notes.append("value list -> CHECK IN")
                else:
                    c.checks.append(Check("regex", pattern=rx))
                    c.notes.append("value_regex -> CHECK ~")

    def apply_audit_columns(self) -> None:
        spec = self.conv["audit_columns"]
        for t in self.tables.values():
            audit_cols = []
            for std, s in spec.items():
                existing = next((t.col(n) for n in s["candidates"] if t.has(n)), None)
                if existing:
                    if existing.name != std:
                        existing.notes.append(f"renamed {existing.name} -> {std}")
                        existing.origin = "renamed"
                    existing.name = std
                    col = existing
                else:
                    col = Column(name=std, pg_type="", origin="added")
                    col.notes.append("standard audit column added")
                col.pg_type, col.default, col.description = s["type"], s["default"], s["description"]
                col.nullable, col.is_audit, col.not_null_reason = False, True, "audit column"
                col.checks = []
                audit_cols.append(col)
            t.columns = [c for c in t.columns if c not in audit_cols] + audit_cols
            leftovers = [n for s in spec.values() for n in s["candidates"] if n not in spec and t.has(n)]
            for n in leftovers:
                self.log("audit", f"{t.key}.{n}",
                         "Kept as a business column (a higher-priority candidate was mapped to the standard audit column).")

    def apply_defect_fixes(self) -> None:
        for key, cols in (self.fixes.get("add_columns") or {}).items():
            t = self.tables[key]
            n_audit = sum(c.is_audit for c in t.columns)
            for spec in cols:
                c = Column(name=spec["name"], pg_type=spec["type"], description=spec["description"], origin="added")
                if "ref" in spec:
                    c.ref = self.make_ref(t, spec["ref"])
                if "values" in spec:
                    c.checks.append(Check("in", values=spec["values"]))
                if "regex" in spec:
                    c.checks.append(Check("regex", pattern=spec["regex"]))
                c.notes.append("added: " + spec["reason"])
                t.columns.insert(len(t.columns) - n_audit, c)
                self.log("defect_fix", f"{key}.{c.name}", f"Added column ({c.pg_type}).", spec["reason"])
        for key, fix in (self.fixes.get("fix_descriptions") or {}).items():
            d, p, col = key.split(".")
            c = self.tables[f"{d}.{p}"].col(col)
            self.log("defect_fix", key,
                     f"Description corrected to: {fix['description']} Business name: {fix['business_name']}.",
                     f"MVM ({c.glossary}): {c.description[:160]}")
            c.description, c.glossary = fix["description"], fix["business_name"]

    def apply_type_overrides(self) -> None:
        for key, spec in self.types.items():
            d, p, col = key.split(".")
            c = self.tables[f"{d}.{p}"].col(col)
            c.pg_type = spec["pg_type"]
            self.log("type", key, f"{c.mvm['type']} -> {spec['pg_type']}", spec["reason"])

    def apply_partitioning(self) -> None:
        for key, col in self.partitioned.items():
            t = self.tables[key]
            pc = t.col(col)
            t.partition_key = col
            pc.nullable, pc.not_null_reason = False, "partition key"
            self.log("partitioning", key, f"PARTITION BY RANGE ({col}), monthly; PK ({t.pk.name}, {col}).",
                     "High-volume raw event data; PostgreSQL requires the partition key in the PK.")
        for t in self.tables.values():
            for c in t.columns:
                if c.ref and c.ref.reason == "partitioned_target":
                    self.log("soft_ref", f"{t.key}.{c.name}",
                             f"Not enforced: target {c.ref.target_fqn} is partitioned.",
                             "An FK to a partitioned table must include its partition key, which the source row does not carry.")

    def apply_nullability(self) -> None:
        nl = self.nulls
        parent = re.compile(nl["parent_fk_pattern"])
        parent_ex = re.compile(nl["parent_fk_exclude_pattern"], re.I)
        bool_null = re.compile(nl["boolean_nullable_pattern"], re.I)
        hint = re.compile(nl["nullable_hint_pattern"], re.I)
        for t in self.tables.values():
            for c in t.columns:
                if c.is_pk or c.is_audit or c.name == t.partition_key or not c.mvm:
                    continue
                desc = c.mvm["description"]
                if (c.ref and c.mvm["reference"] != LLM_LINK and parent.search(desc)
                        and not parent_ex.search(desc) and c.ref.target_table != t.name):
                    c.nullable, c.not_null_reason = False, "parent reference"
                elif c.pg_type == "boolean" and not bool_null.search(desc):
                    c.nullable, c.default, c.not_null_reason = False, "false", "boolean flag"
                if not c.nullable and hint.search(desc):
                    c.nullable, c.not_null_reason = True, ""
                    if c.pg_type == "boolean":
                        c.default = None
        for key, reason in (nl.get("force_not_null") or {}).items():
            d, p, col = key.split(".")
            c = self.tables[f"{d}.{p}"].col(col)
            c.nullable, c.not_null_reason = False, f"override: {reason}"
        for key, reason in (nl.get("force_nullable") or {}).items():
            d, p, col = key.split(".")
            c = self.tables[f"{d}.{p}"].col(col)
            c.nullable, c.not_null_reason = True, ""
            self.log("nullability", key, "Forced nullable.", reason)

    def apply_table_rules(self) -> None:
        missing = set(self.tables) - set(self.rules)
        if missing:
            raise ValueError(f"table_rules.yaml lacks: {sorted(missing)}")
        for key, rule in self.rules.items():
            t = self.tables[key]
            for cols in rule.get("unique") or []:
                for n in cols:
                    t.col(n).nullable, t.col(n).not_null_reason = False, "business key"
                t.uniques.append(cols)
            for n in rule.get("required") or []:
                t.col(n).nullable, t.col(n).not_null_reason = False, "identifying attribute"
            if s := rule.get("status"):
                t.col(s).nullable, t.col(s).not_null_reason = False, "lifecycle status"

    def apply_ranges(self) -> None:
        r = self.conv["ranges"]
        pct, nn = r["percentage"], r["non_negative"]
        for t in self.tables.values():
            for c in t.columns:
                if c.ref or c.is_pk or c.code_set or not c.pg_type.startswith(NUMERIC_TYPES):
                    continue
                if re.search(pct["name_pattern"], c.name) and not re.search(pct["exclude_pattern"], c.name):
                    c.checks.append(Check("range", min=pct["min"], max=pct["max"]))
                elif re.search(nn["name_pattern"], c.name) and not re.search(nn["exclude_pattern"], c.name):
                    c.checks.append(Check("range", min=nn["min"]))

    def apply_date_pairs(self) -> None:
        dp = self.conv["date_pairs"]
        for t in self.tables.values():
            by_name = {c.name: c for c in t.columns}
            for c in t.columns:
                tokens = c.name.split("_")
                for i, tok in enumerate(tokens):
                    if tok in dp["start_tokens"]:
                        end = "_".join(tokens[:i] + [dp["end_token"]] + tokens[i + 1:])
                        e = by_name.get(end)
                        if e and e.pg_type == c.pg_type and c.pg_type in ("date", "timestamptz"):
                            t.date_pairs.append((c.name, end))

    def clean_descriptions(self) -> None:
        rules = [(re.compile(x["pattern"]), x["replace"]) for x in self.conv["description_cleanup"]]
        stale = re.compile(r"^Foreign key linking to (\w+\.\w+)")
        renamed = Counter()
        for t in self.tables.values():
            for c in t.columns:
                if c.is_audit:
                    continue
                d = c.description
                if c.ref and (m := stale.match(d)) and m.group(1) != c.ref.target_fqn:
                    renamed[(m.group(1), c.ref.target_fqn)] += 1
                    d = stale.sub(f"Foreign key linking to {c.ref.target_fqn}", d)
                for rx, rep in rules:
                    d = rx.sub(rep, d)
                d = re.sub(r"\.\.+", ".", d).strip()
                c.description = d
        for (said, real), n in sorted(renamed.items()):
            self.log("defect_fix", said, f"FK descriptions naming `{said}` rewritten to the actual target `{real}` ({n} columns).",
                     "Stale table name in MVM description text; the CSV foreign_key_to is authoritative.")

    def validate(self) -> None:
        names = [t.name for t in self.tables.values()]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"table names must be globally unique: {dupes}")
        for t in self.tables.values():
            cols = [c.name for c in t.columns]
            if len(cols) != len(set(cols)):
                raise ValueError(f"{t.key}: duplicate columns {[c for c in cols if cols.count(c) > 1]}")
            for c in t.columns:
                if c.code_set and c.pg_type != "text":
                    raise ValueError(f"{t.key}.{c.name}: code-set column must be text")


def label(code: str, acronyms: set[str]) -> str:
    return " ".join(w.upper() if w.lower() in acronyms else w.capitalize() for w in re.split(r"[_\s]+", code) if w)


def build_model() -> Model:
    return Builder().build()
