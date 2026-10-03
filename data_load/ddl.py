"""Split schema.sql into the groups the pipeline runs at different moments."""

import re
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_SQL = Path(__file__).with_name("schema.sql")


@dataclass
class SchemaPlan:
    data_tables: dict[str, str] = field(default_factory=dict)  # "transactions" -> DDL
    roles: dict[str, str] = field(default_factory=dict)  # "ll_read" -> CREATE ROLE
    grants: list[str] = field(default_factory=list)  # re-applied after every load
    indexes: list[str] = field(default_factory=list)  # rebuilt after every load


def split_statements(sql: str) -> list[str]:
    """Drop '--' comments, split on ';', collapse whitespace."""
    without_comments = re.sub(r"--[^\n]*", "", sql)
    return [" ".join(s.split()) for s in without_comments.split(";") if s.strip()]


def load_plan(sql: str | None = None) -> SchemaPlan:
    if sql is None:
        sql = SCHEMA_SQL.read_text(encoding="utf-8")
    plan = SchemaPlan()
    for stmt in split_statements(sql):
        if m := re.match(r"CREATE TABLE (\w+) \(", stmt):
            plan.data_tables[m[1]] = stmt
        elif m := re.fullmatch(r"CREATE ROLE (\w+) WITH LOGIN", stmt):
            plan.roles[m[1]] = stmt
        elif stmt.startswith("GRANT "):
            plan.grants.append(stmt)
        elif re.match(r"CREATE INDEX ASYNC \w+ ON \w+ \(", stmt):
            plan.indexes.append(stmt)
        else:
            raise ValueError(f"schema.sql: unclassified statement: {stmt[:80]}")
    return plan


def varchar_limits(ddl: str) -> dict[str, int]:
    """column -> n for every varchar(n) column of one CREATE TABLE statement."""
    return {m[1]: int(m[2]) for m in re.finditer(r"(\w+) varchar\((\d+)\)", ddl)}
