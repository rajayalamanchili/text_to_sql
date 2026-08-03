"""Schema enumeration service (FR-001).

Enumerates every table and column visible on an already-open database
connection via `information_schema`, capturing only structural metadata
(data type, cardinality ratio) — never raw row-level values, and no LLM
is ever called from this module. `cardinality_ratio` is
`distinct_count / row_count` per column (data-model.md#ColumnClassification),
computed with `count(DISTINCT ...)` so no individual value is read into
the application.

Connection lifecycle (opening/closing per `DomainConfig.database_url`) is
the caller's responsibility (e.g. the `/schema/enumerate` endpoint) — this
module only accepts an open connection, per FR-001's "accept a database
connection."
"""

from __future__ import annotations

import psycopg
from psycopg import sql
from pydantic import BaseModel, Field

_TABLES_QUERY = """
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    ORDER BY table_name
"""

_COLUMNS_QUERY = """
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = %s
    ORDER BY ordinal_position
"""


class ColumnSchema(BaseModel):
    """One column's structural metadata, no row-level values (FR-001)."""

    model_config = {"frozen": True}

    column_name: str
    data_type: str
    cardinality_ratio: float = Field(ge=0.0, le=1.0)


class TableSchema(BaseModel):
    model_config = {"frozen": True}

    table_name: str
    columns: list[ColumnSchema]


class DomainSchemaSnapshot(BaseModel):
    model_config = {"frozen": True}

    domain: str
    tables: list[TableSchema]


def enumerate_schema(domain_name: str, conn: psycopg.Connection) -> DomainSchemaSnapshot:
    """Enumerate all base tables/columns visible on `conn`'s `public`
    schema. Issues only metadata/aggregate queries (`information_schema`,
    `count(*)`, `count(DISTINCT col)`) — never `SELECT <col>` — so no raw
    value is ever read out of the database."""
    table_names = _list_base_tables(conn)
    tables = [_enumerate_table(conn, table_name) for table_name in table_names]
    return DomainSchemaSnapshot(domain=domain_name, tables=tables)


def _list_base_tables(conn: psycopg.Connection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(_TABLES_QUERY)
        return [row[0] for row in cur.fetchall()]


def _enumerate_table(conn: psycopg.Connection, table_name: str) -> TableSchema:
    with conn.cursor() as cur:
        cur.execute(_COLUMNS_QUERY, (table_name,))
        column_rows = cur.fetchall()

        row_count = (
            _scalar(cur, sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table_name)))
            if column_rows
            else 0
        )

        columns = [
            ColumnSchema(
                column_name=column_name,
                data_type=data_type,
                cardinality_ratio=_cardinality_ratio(cur, table_name, column_name, row_count),
            )
            for column_name, data_type in column_rows
        ]
    return TableSchema(table_name=table_name, columns=columns)


def _cardinality_ratio(
    cur: psycopg.Cursor, table_name: str, column_name: str, row_count: int
) -> float:
    if row_count == 0:
        return 0.0
    distinct_count = _scalar(
        cur,
        sql.SQL("SELECT count(DISTINCT {}) FROM {}").format(
            sql.Identifier(column_name), sql.Identifier(table_name)
        ),
    )
    return distinct_count / row_count


def _scalar(cur: psycopg.Cursor, query: sql.Composed) -> int:
    cur.execute(query)
    return cur.fetchone()[0]
