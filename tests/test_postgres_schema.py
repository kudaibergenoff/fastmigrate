from contextlib import contextmanager
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import BigInteger, MetaData, Table, inspect, select, text
from sqlalchemy.exc import IntegrityError

from fastmigrate import MigrationRunner, Schema
from fastmigrate.schema import _connection


pytestmark = pytest.mark.postgres


@contextmanager
def schema_transaction(engine):
    with engine.begin() as conn:
        token = _connection.set(conn)
        try:
            yield conn
        finally:
            _connection.reset(token)


def test_postgres_types_defaults_and_comments(postgres_engine):
    with schema_transaction(postgres_engine) as conn:
        Schema.create("types", lambda t: (
            t.id(), t.uuid("public_id"), t.decimal("amount", 12, 2),
            t.jsonb("document"), t.binary("data"), t.integer("age").unsigned(),
            t.string("code").comment("External user's code"), t.timestamps(), t.soft_deletes(),
        ))
        table = Table("types", MetaData(), autoload_with=conn)
        public_id = uuid4()
        conn.execute(table.insert().values(
            public_id=public_id, amount=Decimal("12.34"), document={"key": [1]},
            data=b"\x00\xff", age=0, code="x",
        ))
        row = conn.execute(select(table)).mappings().one()
        assert row["public_id"] == public_id
        assert row["amount"] == Decimal("12.34")
        assert row["document"] == {"key": [1]}
        assert row["data"] == b"\x00\xff"
        assert row["created_at"].tzinfo is not None
        assert row["deleted_at"] is None
        columns = {col["name"]: col for col in inspect(conn).get_columns("types")}
        assert columns["code"]["comment"] == "External user's code"
        assert not columns["code"]["nullable"]
    with pytest.raises(IntegrityError):
        with postgres_engine.begin() as conn:
            conn.execute(table.insert().values(
                public_id=uuid4(), amount=0, document={}, data=b"", age=-1, code="bad",
            ))


def test_postgres_schema_rename_and_drop(postgres_engine):
    with schema_transaction(postgres_engine):
        assert not Schema.has_table("users")
        assert not Schema.has_column("users", "id")
        Schema.create("users", lambda t: (t.id(), t.string("email")))
        assert Schema.has_column("users", "email")
        Schema.rename("users", 'customer"records')
        assert Schema.has_table('customer"records')
        assert not Schema.has_table("users")
        Schema.drop('customer"records')
        Schema.drop_if_exists('customer"records')
        assert not Schema.has_table('customer"records')


def test_postgres_add_drop_rename_and_index(postgres_engine):
    with schema_transaction(postgres_engine) as conn:
        Schema.create("users", lambda t: (t.id(), t.string("email")))
        Schema.table("users", lambda t: (
            t.string("phone").nullable().index(), t.boolean("verified").default(False),
            t.unique(["email"], "users_email_unique"),
        ))
        conn.execute(text("INSERT INTO users (email) VALUES ('first')"))
        assert conn.execute(text("SELECT phone, verified FROM users")).one() == (None, False)
        assert any(item["name"] == "users_phone_index" for item in inspect(conn).get_indexes("users"))
        Schema.table("users", lambda t: (
            t.drop_index("users_phone_index"), t.rename_column("phone", "mobile"),
            t.drop_unique("users_email_unique"),
        ))
        conn.execute(text("INSERT INTO users (email) VALUES ('first')"))
        Schema.table("users", lambda t: (t.drop_column("mobile"), t.drop_column("verified")))
        assert not Schema.has_column("users", "mobile")
        assert [col["name"] for col in inspect(conn).get_columns("users")] == ["id", "email"]


def test_postgres_change_type_nullable_default_and_comment(postgres_engine):
    with schema_transaction(postgres_engine) as conn:
        Schema.create("users", lambda t: (
            t.id(), t.integer("quantity").default(1), t.string("name").nullable(),
        ))
        conn.execute(text("INSERT INTO users DEFAULT VALUES"))
        Schema.table("users", lambda t: (
            t.big_integer("quantity").nullable().default(0).comment("Count").change(),
            t.string("name", 100).change(),
        ))
        columns = {col["name"]: col for col in inspect(conn).get_columns("users")}
        assert isinstance(columns["quantity"]["type"], BigInteger)
        assert columns["quantity"]["nullable"]
        assert columns["quantity"]["comment"] == "Count"
        assert columns["name"]["nullable"]  # Unspecified modifiers are preserved.
        assert columns["name"]["type"].length == 100
        conn.execute(text("INSERT INTO users DEFAULT VALUES"))
        assert conn.execute(text("SELECT quantity FROM users ORDER BY id")).scalars().all() == [1, 0]
        Schema.table("users", lambda t: t.big_integer("quantity").drop_default().nullable(False).change())
        column = next(col for col in inspect(conn).get_columns("users") if col["name"] == "quantity")
        assert column["default"] is None
        assert not column["nullable"]


def test_postgres_type_change_casts_existing_values(postgres_engine):
    with schema_transaction(postgres_engine) as conn:
        Schema.create("codes", lambda t: (t.id(), t.string("value")))
        conn.execute(text("INSERT INTO codes (value) VALUES ('123')"))
        Schema.table("codes", lambda t: t.integer("value").change())
        assert conn.execute(text("SELECT value FROM codes")).scalar_one() == 123


def test_failed_alter_migration_restores_schema_and_history(postgres_engine, tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    runner = MigrationRunner(postgres_engine, directory)
    runner.migrate()
    with schema_transaction(postgres_engine):
        Schema.create("users", lambda t: t.id())
    (directory / "001_bad.py").write_text(
        "from fastmigrate import Migration, Schema\n"
        "class AddPhone(Migration):\n"
        "    def up(self):\n"
        "        Schema.table('users', lambda t: t.string('phone').nullable())\n"
        "        raise RuntimeError('after alter')\n"
        "    def down(self):\n"
        "        Schema.table('users', lambda t: t.drop_column('phone'))\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="after alter"):
        runner.migrate()
    with schema_transaction(postgres_engine) as conn:
        assert not Schema.has_column("users", "phone")
        assert conn.execute(text("SELECT COUNT(*) FROM migrations")).scalar_one() == 0
