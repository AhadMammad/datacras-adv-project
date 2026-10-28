"""Coverage and consistency tests for the generated OLTP models (run `uv run advgen build` first)."""
import csv
import re

import pytest

from advgen.build import ENUM_RE, ROOT, build_model
from advgen.emit_smoke import regex_sample

MAPPING = ROOT / "mapping" / "mvm_to_oltp_mapping.csv"
SOFT_REFS = ROOT / "mapping" / "cross_system_refs.csv"
PHYSICAL = ROOT / "models" / "physical"


@pytest.fixture(scope="module")
def model():
    return build_model()


def read_csv(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def test_every_mvm_attribute_is_mapped(model):
    mapped = {(r["mvm_domain"], r["mvm_product"], r["mvm_column"]) for r in read_csv(MAPPING)}
    source = {(r["domain"], r["product"], r["column_name"]) for r in model.mvm_rows}
    assert len(source) == 3760
    assert source == mapped


def test_every_mvm_relationship_is_enforced_or_soft(model):
    soft = {(r["from_table"], r["from_column"]) for r in read_csv(SOFT_REFS)}
    enforced = soft_count = 0
    for t in model.tables.values():
        for c in t.columns:
            if not (c.mvm and c.mvm["foreign_key_to"]):
                continue
            assert c.ref is not None, f"{t.key}.{c.name} lost its reference"
            if c.ref.enforced:
                enforced += 1
                fk_sql = (PHYSICAL / model.systems[t.system].database / "ddl" / "040_constraints_fk.sql").read_text()
                assert f"ALTER TABLE {t.fqn} ADD CONSTRAINT" in fk_sql and f"FOREIGN KEY ({c.name})" in fk_sql
            else:
                soft_count += 1
                assert (t.fqn, c.name) in soft
    assert enforced + soft_count == 815


def test_every_enum_candidate_has_a_code_set(model):
    candidates = [(r["domain"], r["product"], r["column_name"]) for r in model.mvm_rows
                  if ENUM_RE.search(r["description"])]
    assert len(candidates) == 140
    for d, p, col in candidates:
        t = model.tables[f"{d}.{p}"]
        c = next(c for c in t.columns if c.mvm and c.mvm["column_name"] == col)
        assert c.code_set, f"{d}.{p}.{col}"
        ddl = (PHYSICAL / model.systems[t.system].database / "ddl" / "020_ref_tables.sql").read_text()
        assert f"CREATE TABLE ref.{c.code_set} (" in ddl


def test_every_table_has_uuid_pk_and_audit_columns(model):
    for t in model.tables.values():
        assert t.pk.pg_type == "uuid" and t.pk.default == "uuidv7()"
        names = [c.name for c in t.columns]
        assert names[-4:] == ["created_at", "created_by", "updated_at", "updated_by"], t.key


def test_cross_system_references_are_never_enforced(model):
    for t in model.tables.values():
        for c in t.columns:
            if c.ref and c.ref.target_system != t.system:
                assert not c.ref.enforced


def test_constraint_identifiers_fit_postgres_limit():
    for path in PHYSICAL.glob("*/ddl/*.sql"):
        for name in re.findall(r"(?:CONSTRAINT|INDEX|TRIGGER)\s+(\w+)", path.read_text()):
            assert len(name) <= 63, f"{path.name}: {name}"


def test_regex_checks_have_valid_samples(model):
    for t in model.tables.values():
        for c in t.columns:
            for ch in c.checks:
                if ch.kind == "regex":
                    assert re.search(ch.pattern, regex_sample(ch.pattern))


def test_build_is_deterministic():
    a, b = build_model(), build_model()
    assert [(t.key, [(c.name, c.pg_type, c.nullable) for c in t.columns]) for t in a.tables.values()] == \
           [(t.key, [(c.name, c.pg_type, c.nullable) for c in t.columns]) for t in b.tables.values()]
