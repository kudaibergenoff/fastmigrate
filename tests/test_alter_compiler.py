from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import MetaData, create_engine, select
from sqlalchemy.dialects import postgresql

from fastmigrate import Blueprint
from fastmigrate.compiler import alter_statements


def sql_for(blueprint):
    dialect = postgresql.dialect()
    return [str(statement.compile(dialect=dialect)) for statement in alter_statements(blueprint, dialect)]


def test_add_columns_quotes_defaults_comments_and_identifiers():
    b = Blueprint('table"name', MetaData(), alter=True)
    b.string('column"name').default("O'Reilly").comment("User's code")
    sql = sql_for(b)
    assert sql[0] == 'ALTER TABLE "table""name" ADD COLUMN "column""name" VARCHAR(255) DEFAULT \'O\'\'Reilly\' NOT NULL'
    assert sql[1] == 'COMMENT ON COLUMN "table""name"."column""name" IS \'User\'\'s code\''


def test_change_type_nullable_and_default():
    b = Blueprint("users", MetaData(), alter=True)
    b.integer("age").nullable(False).default(18).change()
    assert sql_for(b) == [
        "ALTER TABLE users ALTER COLUMN age TYPE INTEGER USING CAST(age AS INTEGER), "
        "ALTER COLUMN age SET NOT NULL, ALTER COLUMN age SET DEFAULT '18'",
    ]


def test_unspecified_modifiers_are_preserved_on_change():
    b = Blueprint("users", MetaData(), alter=True)
    b.string("name", 100).change()
    assert sql_for(b) == [
        "ALTER TABLE users ALTER COLUMN name TYPE VARCHAR(100) USING CAST(name AS VARCHAR(100))",
    ]


def test_drop_default_and_nullable():
    b = Blueprint("users", MetaData(), alter=True)
    b.integer("age").nullable().drop_default().change()
    assert "ALTER COLUMN age DROP NOT NULL, ALTER COLUMN age DROP DEFAULT" in sql_for(b)[0]


def test_add_and_drop_named_constraints_and_indexes():
    b = Blueprint("users", MetaData(), alter=True)
    b.unique(["tenant_id", "email"], "users_tenant_email_unique")
    b.index(["tenant_id", "name"], "users_lookup")
    b.drop_constraint('old"constraint')
    b.drop_index('old"index')
    sql = sql_for(b)
    assert sql[0] == 'ALTER TABLE users DROP CONSTRAINT "old""constraint"'
    assert sql[1] == 'DROP INDEX "old""index"'
    assert sql[2] == "ALTER TABLE users ADD CONSTRAINT users_tenant_email_unique UNIQUE (tenant_id, email)"
    assert sql[3] == "CREATE INDEX users_lookup ON users (tenant_id, name)"


def test_rename_and_drop_identifiers_cannot_add_statements():
    b = Blueprint('table"name', MetaData(), alter=True)
    b.rename_column("old", 'new"; DROP TABLE users; --')
    b.drop_column('old"column')
    assert sql_for(b) == [
        'ALTER TABLE "table""name" RENAME COLUMN "old" TO "new""; DROP TABLE users; --"',
        'ALTER TABLE "table""name" DROP COLUMN "old""column"',
    ]


def test_new_types_round_trip_on_smoke_backend():
    b = Blueprint("types", MetaData())
    b.id()
    b.uuid("public_id")
    b.decimal("amount", 12, 2)
    b.date("birthday")
    b.date_time("appointment")
    b.jsonb("document")
    b.binary("data")
    b.small_integer("count")
    b.float("ratio")
    b.soft_deletes()
    values = {
        "public_id": uuid4(), "amount": Decimal("12.34"), "birthday": date(2000, 1, 1),
        "appointment": datetime(2026, 10, 15, 12, 0), "document": {"nested": [1, 2]},
        "data": b"\x00\xff", "count": 5, "ratio": 0.5,
    }
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            b.table.create(conn)
            conn.execute(b.table.insert().values(**values))
            row = conn.execute(select(b.table)).mappings().one()
            assert {key: row[key] for key in values} == values
            assert row["deleted_at"] is None
    finally:
        engine.dispose()
