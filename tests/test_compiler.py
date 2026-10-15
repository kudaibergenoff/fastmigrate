from sqlalchemy import MetaData, Table
from sqlalchemy.dialects import postgresql

from fastmigrate.compiler import DropTables


def test_drop_tables_quotes_identifiers_and_never_cascades():
    tables = [
        Table('table";DROP SCHEMA other;--', MetaData(), schema='schema"name'),
        Table("another", MetaData(), schema="public"),
    ]
    sql = str(DropTables(tables).compile(dialect=postgresql.dialect()))
    assert sql == 'DROP TABLE "schema""name"."table"";DROP SCHEMA other;--", public.another'
    assert "CASCADE" not in sql
