import pytest
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, NoSuchTableError
from sqlalchemy.schema import CreateTable

from fastmigrate import Blueprint, Schema
from fastmigrate.schema import _connection


@pytest.fixture
def connection():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            token = _connection.set(conn)
            try:
                yield conn
            finally:
                _connection.reset(token)
    finally:
        engine.dispose()


def test_all_postgres_types_compile():
    b = Blueprint("types", MetaData())
    b.id()
    b.uuid("uuid")
    b.string("name", 120)
    b.text("body")
    b.integer("count")
    b.big_integer("large")
    b.small_integer("small")
    b.boolean("enabled")
    b.decimal("amount", 12, 2)
    b.float("ratio")
    b.date("birthday")
    b.date_time("appointment")
    b.timestamp("published_at")
    b.json("payload")
    b.jsonb("document")
    b.binary("data")
    b.foreign_id("user_id")
    b.timestamps()
    b.soft_deletes()
    sql = str(CreateTable(b.table).compile(dialect=postgresql.dialect()))
    for fragment in ("BIGSERIAL", "UUID", "VARCHAR(120)", "SMALLINT", "NUMERIC(12, 2)", "FLOAT", "DATE", "TIMESTAMP", "JSONB", "BYTEA", "created_at", "deleted_at"):
        assert fragment in sql
    assert b.table.c.deleted_at.nullable
    assert not b.table.c.name.nullable


def test_not_null_and_explicit_nullable_are_enforced(connection):
    Schema.create("users", lambda t: (t.id(), t.string("name"), t.string("phone").nullable()))
    with pytest.raises(IntegrityError):
        connection.execute(text("INSERT INTO users DEFAULT VALUES"))
    connection.execute(text("INSERT INTO users (name) VALUES ('Alice')"))
    assert connection.execute(text("SELECT phone FROM users")).scalar_one() is None


def test_unsigned_is_a_check_constraint(connection):
    Schema.create("users", lambda t: (t.id(), t.integer("age").unsigned().unsigned()))
    with pytest.raises(IntegrityError):
        connection.execute(text("INSERT INTO users (age) VALUES (-1)"))
    connection.execute(text("INSERT INTO users (age) VALUES (0)"))
    constraints = inspect(connection).get_check_constraints("users")
    assert len(constraints) == 1
    assert constraints[0]["name"] == "users_age_unsigned"


def test_unsigned_rejects_non_numeric_columns():
    b = Blueprint("users", MetaData())
    with pytest.raises(TypeError, match="numeric"):
        b.string("code").unsigned()


def test_schema_introspection_rename_and_drop(connection):
    assert not Schema.has_table("users")
    assert not Schema.has_column("users", "id")
    Schema.create("users", lambda t: (t.id(), t.string("email")))
    assert Schema.has_table("users")
    assert Schema.has_column("users", "email")
    assert not Schema.has_column("users", "missing")
    Schema.rename("users", 'customer"records')
    assert not Schema.has_table("users")
    assert Schema.has_column('customer"records', "email")
    Schema.drop('customer"records')
    assert not Schema.has_table('customer"records')
    Schema.drop_if_exists('customer"records')


def test_alter_add_rename_drop_columns_and_indexes(connection):
    Schema.create("users", lambda t: t.id())
    Schema.table("users", lambda t: (
        t.string("phone").nullable().index(),
        t.boolean("verified").default(False),
    ))
    connection.execute(text("INSERT INTO users DEFAULT VALUES"))
    assert connection.execute(text("SELECT phone, verified FROM users")).one() == (None, 0)
    assert inspect(connection).get_indexes("users")[0]["name"] == "users_phone_index"
    Schema.table("users", lambda t: (
        t.drop_index("users_phone_index"), t.rename_column("phone", "mobile"),
    ))
    assert Schema.has_column("users", "mobile")
    assert not Schema.has_column("users", "phone")
    Schema.table("users", lambda t: (t.drop_column("mobile"), t.drop_column("verified")))
    assert [c["name"] for c in inspect(connection).get_columns("users")] == ["id"]


def test_index_can_reference_existing_columns(connection):
    Schema.create("users", lambda t: (t.id(), t.string("email"), t.string("name")))
    Schema.table("users", lambda t: t.index(["email", "name"], "lookup_users"))
    assert inspect(connection).get_indexes("users")[0]["column_names"] == ["email", "name"]
    Schema.table("users", lambda t: t.drop_index("lookup_users"))
    assert inspect(connection).get_indexes("users") == []


def test_missing_alter_table_is_an_error(connection):
    with pytest.raises(NoSuchTableError):
        Schema.table("missing", lambda t: t.string("name"))


def test_sqlite_unsupported_changes_fail_before_any_ddl(connection):
    Schema.create("users", lambda t: (t.id(), t.string("name")))
    with pytest.raises(NotImplementedError, match="PostgreSQL"):
        Schema.table("users", lambda t: (t.string("phone").nullable(), t.string("name", 100).change()))
    assert not Schema.has_column("users", "phone")


def test_change_requires_schema_table():
    b = Blueprint("users", MetaData())
    with pytest.raises(ValueError, match="Schema.table"):
        b.string("name").change()


def test_generated_names_fit_postgres_identifier_limit():
    b = Blueprint("table_" + "a" * 50, MetaData())
    b.string("column_" + "b" * 50).unique().index()
    index, = b.table.indexes
    assert len(index.name.encode("utf-8")) <= 63
    b2 = Blueprint(b.table.name, MetaData())
    b2.string("column_" + "b" * 50).index()
    assert next(iter(b2.table.indexes)).name == index.name
