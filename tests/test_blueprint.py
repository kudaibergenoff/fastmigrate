import pytest
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from fastmigrate import Blueprint


@pytest.fixture
def engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    yield engine
    engine.dispose()


def test_unique_rejects_duplicates(engine):
    blueprint = Blueprint("users", MetaData())
    blueprint.id()
    blueprint.string("email").unique()
    blueprint.table.create(engine)

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (email) VALUES ('same@example.com')"))
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (email) VALUES ('same@example.com')"))


def test_index_is_created(engine):
    blueprint = Blueprint("users", MetaData())
    blueprint.string("name").index()
    blueprint.table.create(engine)

    indexes = inspect(engine).get_indexes("users")
    assert len(indexes) == 1
    assert indexes[0]["column_names"] == ["name"]
    assert not indexes[0]["unique"]


@pytest.mark.parametrize("modifiers", [
    ("index", "unique"),
    ("unique", "index"),
    ("unique", "unique", "index", "index"),
])
def test_unique_index_is_independent_of_modifier_order(engine, modifiers):
    blueprint = Blueprint("users", MetaData())
    column = blueprint.string("email")
    for modifier in modifiers:
        getattr(column, modifier)()
    blueprint.table.create(engine)

    indexes = inspect(engine).get_indexes("users")
    assert len(indexes) == 1
    assert indexes[0]["column_names"] == ["email"]
    assert indexes[0]["unique"]
    assert inspect(engine).get_unique_constraints("users") == []
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (email) VALUES ('duplicate')"))
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (email) VALUES ('duplicate')"))


def test_repeated_unique_does_not_duplicate_constraint(engine):
    blueprint = Blueprint("users", MetaData())
    blueprint.string("email").unique().unique()
    blueprint.table.create(engine)
    constraints = inspect(engine).get_unique_constraints("users")
    assert len(constraints) == 1
    assert constraints[0]["column_names"] == ["email"]


def test_defaults_and_nullable_are_database_properties(engine):
    blueprint = Blueprint("settings", MetaData())
    blueprint.id()
    blueprint.string("description").nullable()
    blueprint.string("label").default("O'Reilly")
    blueprint.integer("quantity").default(7)
    blueprint.boolean("enabled").default(False)
    blueprint.timestamps()
    blueprint.table.create(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO settings DEFAULT VALUES"))
        row = conn.execute(text("SELECT * FROM settings")).mappings().one()
    assert row["description"] is None
    assert row["label"] == "O'Reilly"
    assert row["quantity"] == 7
    assert row["enabled"] == 0
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


@pytest.mark.parametrize("value", [None, {}, [], object()])
def test_unsupported_default_is_rejected(value):
    blueprint = Blueprint("settings", MetaData())
    with pytest.raises(TypeError, match="Unsupported server default"):
        blueprint.string("value").default(value)


def test_basic_column_types_can_be_created(engine):
    blueprint = Blueprint("types", MetaData())
    blueprint.id()
    blueprint.string("name", 20)
    blueprint.integer("quantity")
    blueprint.big_integer("large_number")
    blueprint.text("description")
    blueprint.boolean("enabled")
    blueprint.json("payload")
    blueprint.table.create(engine)
    assert {c["name"] for c in inspect(engine).get_columns("types")} == {
        "id", "name", "quantity", "large_number", "description", "enabled", "payload",
    }
