"""Intermediate representation of the OLTP source-system models."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ref:
    """Reference from a column to another table's primary key."""
    target_system: str
    target_schema: str
    target_table: str
    target_column: str
    enforced: bool
    reason: str  # same_system | cross_system | partitioned_target
    target_database: str = ""

    @property
    def target_fqn(self) -> str:
        return f"{self.target_schema}.{self.target_table}"


@dataclass
class Check:
    kind: str  # in | regex | range
    values: list[str] = field(default_factory=list)
    pattern: str = ""
    min: float | None = None
    max: float | None = None


@dataclass
class Column:
    name: str
    pg_type: str
    description: str = ""
    nullable: bool = True
    default: str | None = None
    is_pk: bool = False
    ref: Ref | None = None
    code_set: str | None = None
    checks: list[Check] = field(default_factory=list)
    glossary: str = ""
    tags: str = ""
    origin: str = "mvm"  # mvm | renamed | added
    mvm: dict | None = None  # source CSV row (lineage)
    notes: list[str] = field(default_factory=list)  # transformation notes
    not_null_reason: str = ""
    is_audit: bool = False

    @property
    def mvm_name(self) -> str:
        return self.mvm["column_name"] if self.mvm else ""


@dataclass
class Table:
    system: str
    schema: str
    name: str
    subdomain: str
    data_type: str  # master_data | transactional_data | reference_data | association_data
    description: str
    columns: list[Column] = field(default_factory=list)
    uniques: list[list[str]] = field(default_factory=list)
    date_pairs: list[tuple[str, str]] = field(default_factory=list)
    partition_key: str | None = None
    origin: str = "mvm"  # mvm | code_set

    @property
    def key(self) -> str:
        """MVM key <domain>.<product> (schema == MVM domain)."""
        return f"{self.schema}.{self.name}"

    @property
    def fqn(self) -> str:
        return f"{self.schema}.{self.name}"

    @property
    def pk(self) -> Column:
        return next(c for c in self.columns if c.is_pk)

    @property
    def pk_columns(self) -> list[str]:
        cols = [self.pk.name]
        if self.partition_key:
            cols.append(self.partition_key)
        return cols

    def col(self, name: str) -> Column:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(f"{self.key}: no column {name!r}")

    def has(self, name: str) -> bool:
        return any(c.name == name for c in self.columns)


@dataclass
class CodeSet:
    system: str
    name: str
    values: list[str] = field(default_factory=list)
    usages: list[tuple[str, str]] = field(default_factory=list)  # (table key, column)
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def fqn(self) -> str:
        return f"ref.{self.name}"


@dataclass
class System:
    key: str
    database: str
    service: str
    port: int
    mimics: str
    description: str
    tables: list[Table] = field(default_factory=list)
    code_sets: dict[str, CodeSet] = field(default_factory=dict)

    @property
    def schemas(self) -> list[str]:
        seen: list[str] = []
        for t in self.tables:
            if t.schema not in seen:
                seen.append(t.schema)
        return seen

    def subdomains(self) -> list[tuple[str, str]]:
        seen: list[tuple[str, str]] = []
        for t in self.tables:
            if (t.schema, t.subdomain) not in seen:
                seen.append((t.schema, t.subdomain))
        return seen


@dataclass
class Decision:
    category: str
    target: str
    decision: str
    reason: str = ""


@dataclass
class Model:
    systems: dict[str, System]
    tables: dict[str, Table]  # by MVM key
    decisions: list[Decision]
    mvm_rows: list[dict]
    source_sha: str

    def system_of(self, table_key: str) -> System:
        return self.systems[self.tables[table_key].system]
