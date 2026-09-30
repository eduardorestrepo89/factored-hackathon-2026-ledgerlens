"""Split schema.sql into the groups the load runs at different moments."""

import re
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_SQL = Path(__file__).with_name("schema.sql")


@dataclass
class SchemaPlan:
    schemas: list[str] = field(default_factory=list)
    data_tables: dict[str, str] = field(default_factory=dict)  # "bank.x" -> DDL
    views: dict[str, str] = field(default_factory=dict)  # "bank.v" -> DDL
    app_tables: list[str] = field(default_factory=list)
    roles: dict[str, str] = field(default_factory=dict)  # "ll_read" -> CREATE ROLE
    grants: list[str] = field(default_factory=list)
    data_indexes: list[str] = field(default_factory=list)  # rebuilt every load
    app_indexes: dict[str, str] = field(default_factory=dict)  # name -> DDL, once


def split_statements(sql: str) -> list[str]:
    """Drop '--' comments, split on ';', collapse whitespace."""
    without_comments = re.sub(r"--[^\n]*", "", sql)
    return [" ".join(s.split()) for s in without_comments.split(";") if s.strip()]


def load_plan(sql: str | None = None) -> SchemaPlan:
    if sql is None:
        sql = SCHEMA_SQL.read_text(encoding="utf-8")
    plan = SchemaPlan()
    for stmt in split_statements(sql):
        if re.fullmatch(r"CREATE SCHEMA IF NOT EXISTS \w+", stmt):
            plan.schemas.append(stmt)
        elif m := re.match(r"CREATE TABLE ((?:bank|pii)\.\w+) \(", stmt):
            plan.data_tables[m[1]] = stmt
        elif m := re.match(r"CREATE VIEW (\w+\.\w+) AS ", stmt):
            plan.views[m[1]] = stmt
        elif re.match(r"CREATE TABLE IF NOT EXISTS app\.\w+ \(", stmt):
            plan.app_tables.append(stmt)
        elif m := re.fullmatch(r"CREATE ROLE (\w+) WITH LOGIN", stmt):
            plan.roles[m[1]] = stmt
        elif stmt.startswith("GRANT "):
            plan.grants.append(stmt)
        elif m := re.match(r"CREATE INDEX ASYNC (\w+) ON (bank|pii|app)\.", stmt):
            if m[2] == "app":
                plan.app_indexes[m[1]] = stmt
            else:
                plan.data_indexes.append(stmt)
        else:
            raise ValueError(f"schema.sql: unclassified statement: {stmt[:80]}")
    return plan
