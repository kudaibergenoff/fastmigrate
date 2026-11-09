from contextlib import contextmanager

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from fastmigrate import Schema
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


def test_cascade_and_orphan_enforcement(postgres_engine):
    with schema_transaction(postgres_engine) as conn:
        Schema.create("users", lambda t: t.id())
        Schema.create("orders", lambda t: (
            t.id(), t.foreign_id("user_id").constrained("users")
            .on_delete("CASCADE").on_update("CASCADE"),
        ))
        conn.execute(text("INSERT INTO users (id) VALUES (1)"))
        conn.execute(text("INSERT INTO orders (user_id) VALUES (1)"))
    with pytest.raises(IntegrityError):
        with postgres_engine.begin() as conn:
            conn.execute(text("INSERT INTO orders (user_id) VALUES (99)"))
    with postgres_engine.begin() as conn:
        conn.execute(text("UPDATE users SET id=2 WHERE id=1"))
        assert conn.execute(text("SELECT user_id FROM orders")).scalar_one() == 2
        conn.execute(text("DELETE FROM users WHERE id=2"))
        assert conn.execute(text("SELECT COUNT(*) FROM orders")).scalar_one() == 0


def test_set_null(postgres_engine):
    with schema_transaction(postgres_engine) as conn:
        Schema.create("users", lambda t: t.id())
        Schema.create("orders", lambda t: (
            t.id(), t.foreign_id("user_id").constrained("users").on_delete("SET NULL").nullable(),
        ))
        conn.execute(text("INSERT INTO users (id) VALUES (1)"))
        conn.execute(text("INSERT INTO orders (user_id) VALUES (1)"))
        conn.execute(text("DELETE FROM users WHERE id=1"))
        assert conn.execute(text("SELECT user_id FROM orders")).scalar_one() is None


def test_composite_fk_and_drop_by_name(postgres_engine):
    with schema_transaction(postgres_engine) as conn:
        Schema.create("accounts", lambda t: (
            t.integer("tenant_id"), t.string("code"), t.primary(["tenant_id", "code"]),
        ))
        Schema.create("events", lambda t: (
            t.id(), t.integer("tenant_id"), t.string("account_code"),
            t.foreign(["tenant_id", "account_code"], "events_account_foreign")
            .references(["tenant_id", "code"]).on("accounts").on_update("CASCADE"),
        ))
        conn.execute(text("INSERT INTO accounts VALUES (1, 'a')"))
        conn.execute(text("INSERT INTO events (tenant_id, account_code) VALUES (1, 'a')"))
        conn.execute(text("UPDATE accounts SET code='b' WHERE tenant_id=1"))
        assert conn.execute(text("SELECT account_code FROM events")).scalar_one() == "b"
        fk, = inspect(conn).get_foreign_keys("events")
        assert fk["constrained_columns"] == ["tenant_id", "account_code"]
        Schema.table("events", lambda t: t.drop_foreign("events_account_foreign"))
        conn.execute(text("INSERT INTO events (tenant_id, account_code) VALUES (99, 'orphan')"))
        assert inspect(conn).get_foreign_keys("events") == []


def test_alter_adds_foreign_column_once(postgres_engine):
    with schema_transaction(postgres_engine) as conn:
        Schema.create("users", lambda t: t.id())
        Schema.create("orders", lambda t: t.id())
        conn.execute(text("INSERT INTO orders DEFAULT VALUES"))
        Schema.table("orders", lambda t: (
            t.foreign_id("user_id").nullable().constrained("users").on_delete("SET NULL"),
        ))
        fk, = inspect(conn).get_foreign_keys("orders")
        assert fk["name"] == "orders_user_id_foreign"
        conn.execute(text("INSERT INTO users (id) VALUES (1)"))
        conn.execute(text("UPDATE orders SET user_id=1"))
        conn.execute(text("DELETE FROM users WHERE id=1"))
        assert conn.execute(text("SELECT user_id FROM orders")).scalar_one() is None
        Schema.table("orders", lambda t: (t.drop_foreign(["user_id"]), t.drop_column("user_id")))
        assert not Schema.has_column("orders", "user_id")


@pytest.mark.parametrize("foreign_first", [False, True])
def test_existing_nullable_is_used_for_set_null_validation(postgres_engine, foreign_first):
    with schema_transaction(postgres_engine) as conn:
        Schema.create("users", lambda t: t.id())
        Schema.create("orders", lambda t: (t.id(), t.foreign_id("user_id")))
        with pytest.raises(ValueError, match="nullable"):
            Schema.table("orders", lambda t: (
                t.string("new_column").nullable(),
                t.foreign("user_id").references("id").on("users").on_delete("SET NULL"),
            ))
        assert not Schema.has_column("orders", "new_column")
        def make_nullable_and_reference(t):
            if foreign_first:
                t.foreign("user_id").references("id").on("users").on_delete("SET NULL")
            t.big_integer("user_id").nullable().change()
            if not foreign_first:
                t.foreign("user_id").references("id").on("users").on_delete("SET NULL")
        Schema.table("orders", make_nullable_and_reference)
        assert inspect(conn).get_foreign_keys("orders")[0]["options"]["ondelete"] == "SET NULL"


def test_unique_index_and_named_primary(postgres_engine):
    with schema_transaction(postgres_engine) as conn:
        Schema.create("users", lambda t: (
            t.id(), t.integer("tenant_id"), t.string("email"),
            t.unique_index(["tenant_id", "email"], "tenant_email_lookup"),
        ))
        assert inspect(conn).get_pk_constraint("users")["name"] == "users_primary"
        assert any(i["name"] == "tenant_email_lookup" and i["unique"] for i in inspect(conn).get_indexes("users"))
        conn.execute(text("INSERT INTO users (tenant_id, email) VALUES (1, 'a')"))
    with pytest.raises(IntegrityError):
        with postgres_engine.begin() as conn:
            conn.execute(text("INSERT INTO users (tenant_id, email) VALUES (1, 'a')"))


@pytest.mark.parametrize("alter", [False, True])
def test_self_foreign_key_can_use_new_unique_index(postgres_engine, alter):
    def columns(t):
        t.string("code")
        t.unique_index("code")
        t.string("parent_code").nullable().constrained("nodes", "code").on_delete("CASCADE")
    with schema_transaction(postgres_engine) as conn:
        if alter:
            Schema.create("nodes", lambda t: t.id())
            Schema.table("nodes", columns)
        else:
            Schema.create("nodes", lambda t: (t.id(), columns(t)))
        conn.execute(text("INSERT INTO nodes (code) VALUES ('root')"))
        conn.execute(text("INSERT INTO nodes (code, parent_code) VALUES ('child', 'root')"))
        conn.execute(text("DELETE FROM nodes WHERE code='root'"))
        assert conn.execute(text("SELECT COUNT(*) FROM nodes")).scalar_one() == 0
