import pytest
from sqlalchemy import MetaData, create_engine, create_mock_engine, event, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from fastmigrate import Blueprint, Schema
from fastmigrate.compiler import alter_statements
from fastmigrate.schema import _connection


@pytest.fixture
def connection():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi, record):
        dbapi.execute("PRAGMA foreign_keys=ON")

    try:
        with engine.begin() as conn:
            token = _connection.set(conn)
            try:
                yield conn
            finally:
                _connection.reset(token)
    finally:
        engine.dispose()


def test_foreign_id_rejects_orphans_and_delete_cascades(connection):
    Schema.create("users", lambda t: t.id())
    Schema.create("orders", lambda t: (
        t.id(), t.foreign_id("user_id").constrained("users").on_delete("CASCADE"),
    ))
    with pytest.raises(IntegrityError):
        connection.execute(text("INSERT INTO orders (user_id) VALUES (99)"))
    connection.execute(text("INSERT INTO users (id) VALUES (1)"))
    connection.execute(text("INSERT INTO orders (user_id) VALUES (1)"))
    connection.execute(text("DELETE FROM users WHERE id=1"))
    assert connection.execute(text("SELECT COUNT(*) FROM orders")).scalar_one() == 0
    fk, = inspect(connection).get_foreign_keys("orders")
    assert fk["name"] == "orders_user_id_foreign"
    assert fk["referred_table"] == "users"


def test_set_null_accepts_nullable_after_action_and_update_cascade(connection):
    Schema.create("users", lambda t: t.id())
    Schema.create("orders", lambda t: (
        t.id(), t.foreign_id("user_id").constrained("users")
        .on_delete("set null").on_update("CASCADE").nullable(),
    ))
    connection.execute(text("INSERT INTO users (id) VALUES (1)"))
    connection.execute(text("INSERT INTO orders (user_id) VALUES (1)"))
    connection.execute(text("UPDATE users SET id=2 WHERE id=1"))
    assert connection.execute(text("SELECT user_id FROM orders")).scalar_one() == 2
    connection.execute(text("DELETE FROM users WHERE id=2"))
    assert connection.execute(text("SELECT user_id FROM orders")).scalar_one() is None


def test_composite_primary_and_foreign_keys(connection):
    Schema.create("accounts", lambda t: (
        t.integer("tenant_id"), t.string("code"), t.primary(["tenant_id", "code"]),
    ))
    Schema.create("events", lambda t: (
        t.id(), t.integer("tenant_id"), t.string("account_code"),
        t.foreign(["tenant_id", "account_code"]).references(["tenant_id", "code"])
        .on("accounts").on_update("CASCADE").on_delete("CASCADE"),
    ))
    connection.execute(text("INSERT INTO accounts VALUES (1, 'a')"))
    connection.execute(text("INSERT INTO events (tenant_id, account_code) VALUES (1, 'a')"))
    with pytest.raises(IntegrityError):
        connection.execute(text("INSERT INTO events (tenant_id, account_code) VALUES (2, 'a')"))
    connection.execute(text("UPDATE accounts SET code='b' WHERE tenant_id=1"))
    assert connection.execute(text("SELECT account_code FROM events")).scalar_one() == "b"
    assert inspect(connection).get_pk_constraint("accounts")["name"] == "accounts_primary"
    connection.execute(text("DELETE FROM accounts"))
    assert connection.execute(text("SELECT COUNT(*) FROM events")).scalar_one() == 0


def test_self_reference(connection):
    Schema.create("nodes", lambda t: (
        t.id(), t.foreign_id("parent_id").nullable().constrained("nodes").on_delete("CASCADE"),
    ))
    connection.execute(text("INSERT INTO nodes (id) VALUES (1)"))
    connection.execute(text("INSERT INTO nodes (id, parent_id) VALUES (2, 1)"))
    connection.execute(text("DELETE FROM nodes WHERE id=1"))
    assert connection.execute(text("SELECT COUNT(*) FROM nodes")).scalar_one() == 0


def test_unique_composite_index_is_enforced(connection):
    Schema.create("users", lambda t: (
        t.id(), t.integer("tenant_id"), t.string("email"),
        t.unique_index(["tenant_id", "email"]),
    ))
    connection.execute(text("INSERT INTO users (tenant_id, email) VALUES (1, 'a')"))
    connection.execute(text("INSERT INTO users (tenant_id, email) VALUES (2, 'a')"))
    with pytest.raises(IntegrityError):
        connection.execute(text("INSERT INTO users (tenant_id, email) VALUES (1, 'a')"))
    index, = inspect(connection).get_indexes("users")
    assert index["unique"]


def test_foreign_identifiers_are_not_dotted_sql_fragments():
    b = Blueprint('orders"table', MetaData())
    b.foreign_id('user"id').constrained('odd.table', 'id.with.dot', schema='schema"name').on_delete("CASCADE")
    b.validate()
    sql = str(CreateTable(b.table).compile(dialect=postgresql.dialect()))
    assert 'REFERENCES "schema""name"."odd.table" ("id.with.dot") ON DELETE CASCADE' in sql


def test_alter_foreign_key_is_added_once_and_can_be_dropped():
    b = Blueprint("orders", MetaData(), alter=True)
    b.foreign_id("user_id").constrained("users").on_delete("CASCADE")
    b.validate()
    dialect = postgresql.dialect()
    sql = [str(s.compile(dialect=dialect)) for s in alter_statements(b, dialect)]
    assert sql[0] == "ALTER TABLE orders ADD COLUMN user_id BIGINT NOT NULL"
    assert sql[1] == "ALTER TABLE orders ADD CONSTRAINT orders_user_id_foreign FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE"
    b = Blueprint("orders", MetaData(), alter=True)
    b.drop_foreign(["user_id"])
    assert str(alter_statements(b, dialect)[0].compile(dialect=dialect)) == "ALTER TABLE orders DROP CONSTRAINT orders_user_id_foreign"


@pytest.mark.parametrize("action", ["CASCADE; DROP TABLE users", "SET NOTHING", ""])
def test_invalid_actions_fail_before_ddl(action):
    b = Blueprint("orders", MetaData())
    with pytest.raises(ValueError, match="action"):
        b.foreign_id("user_id").constrained("users").on_delete(action)


def test_set_null_on_required_columns_is_rejected_before_create(connection):
    with pytest.raises(ValueError, match="nullable"):
        Schema.create("orders", lambda t: (
            t.id(), t.foreign_id("user_id").constrained("users").on_delete("SET NULL"),
        ))
    assert not inspect(connection).has_table("orders")


def test_foreign_key_arity_and_incomplete_definitions_are_rejected():
    b = Blueprint("orders", MetaData())
    b.integer("a")
    b.integer("b")
    with pytest.raises(ValueError, match="same number"):
        b.foreign(["a", "b"]).references(["id"])
    b = Blueprint("orders", MetaData())
    b.integer("user_id")
    b.foreign("user_id")
    with pytest.raises(ValueError, match="references.*on"):
        b.validate()


def test_foreign_key_survives_changing_its_placeholder_column():
    b = Blueprint("nodes", MetaData(), alter=True)
    b.foreign("parent_id").references("id").on("nodes").on_delete("SET NULL")
    b.big_integer("parent_id").nullable().change()
    b.validate([{"name": "id", "nullable": False}, {"name": "parent_id", "nullable": False}])
    dialect = postgresql.dialect()
    sql = [str(s.compile(dialect=dialect)) for s in alter_statements(b, dialect)]
    assert len(b.table.foreign_key_constraints) == 1
    assert len(sql) == 2
    assert "ADD CONSTRAINT nodes_parent_id_foreign" in sql[-1]


def test_alter_creates_uniqueness_before_foreign_keys():
    b = Blueprint("nodes", MetaData(), alter=True)
    b.string("code")
    b.unique_index("code")
    b.string("parent_code").nullable().constrained("nodes", "code")
    b.validate()
    dialect = postgresql.dialect()
    sql = [str(s.compile(dialect=dialect)) for s in alter_statements(b, dialect)]
    assert sql[-2].startswith("CREATE UNIQUE INDEX")
    assert "FOREIGN KEY" in sql[-1]


def test_create_defers_postgres_self_foreign_key_until_unique_index():
    sql = []
    engine = create_mock_engine("postgresql+psycopg://", lambda statement, *args, **kwargs: sql.append(str(statement.compile(dialect=engine.dialect))))
    token = _connection.set(engine)
    try:
        Schema.create("nodes", lambda t: (
            t.string("code"), t.unique_index("code"),
            t.string("parent_code").nullable().constrained("nodes", "code"),
        ))
    finally:
        _connection.reset(token)
    assert "CREATE TABLE" in sql[0]
    assert "FOREIGN KEY" not in sql[0]
    assert sql[1].startswith("CREATE UNIQUE INDEX")
    assert "ADD CONSTRAINT" in sql[2] and "FOREIGN KEY" in sql[2]


def test_pending_fk_cannot_reference_a_column_renamed_later(connection):
    Schema.create("users", lambda t: t.id())
    Schema.create("orders", lambda t: t.id())
    with pytest.raises(ValueError, match="final name"):
        Schema.table("orders", lambda t: (
            t.foreign_id("old_id").nullable().constrained("users"),
            t.rename_column("old_id", "user_id"),
        ))
    assert not Schema.has_column("orders", "old_id")
    assert not Schema.has_column("orders", "user_id")


def test_fk_can_be_declared_using_final_name_after_rename():
    b = Blueprint("orders", MetaData(), alter=True)
    b.foreign_id("old_id").nullable()
    b.rename_column("old_id", "user_id")
    b.foreign("user_id").references("id").on("users").on_delete("SET NULL")
    b.validate([{"name": "id", "nullable": False}])
    dialect = postgresql.dialect()
    sql = [str(s.compile(dialect=dialect)) for s in alter_statements(b, dialect)]
    assert "FOREIGN KEY(user_id)" in sql[-1]
