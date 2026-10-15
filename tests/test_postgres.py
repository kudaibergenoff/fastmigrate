import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from fastmigrate import MigrationRunner
from fastmigrate.schema import _connection


pytestmark = pytest.mark.postgres


@pytest.fixture
def runner(postgres_engine, tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    return MigrationRunner(postgres_engine, directory)


def write_migration(runner, name, table, *, fail_up=False, fail_down=False):
    up_failure = '        raise RuntimeError("up failed")\n' if fail_up else ""
    down_failure = '        raise RuntimeError("down failed")\n' if fail_down else ""
    path = runner.directory / name
    path.write_text(
        "from fastmigrate import Migration, Schema\n"
        "class Change(Migration):\n"
        "    def up(self):\n"
        f"        Schema.create({table!r}, lambda t: (\n"
        "            t.id(), t.string('email').unique(),\n"
        "            t.string('status').index(), t.boolean('active').default(True)\n"
        "        ))\n"
        f"{up_failure}"
        "    def down(self):\n"
        f"        Schema.drop_if_exists({table!r})\n"
        f"{down_failure}",
        encoding="utf-8",
    )
    return path


def history(runner):
    with runner.engine.connect() as conn:
        return conn.execute(
            select(runner.history).order_by(runner.history.c.migration)
        ).all()


def test_create_history_defaults_constraints_and_drop(runner):
    write_migration(runner, "001_users.py", "users")
    assert runner.migrate() == ["001_users.py"]
    assert runner.migrate() == []
    assert runner.status() == [("001_users.py", True)]
    assert history(runner) == [("001_users.py", 1)]
    inspector = inspect(runner.engine)
    assert inspector.has_table("users")
    assert any(c["column_names"] == ["email"] for c in inspector.get_unique_constraints("users"))
    assert any(i["column_names"] == ["status"] for i in inspector.get_indexes("users"))
    with runner.engine.begin() as conn:
        conn.execute(text("INSERT INTO users (email) VALUES ('same@example.com')"))
        assert conn.execute(text("SELECT active FROM users")).scalar_one() is True
    with pytest.raises(IntegrityError):
        with runner.engine.begin() as conn:
            conn.execute(text("INSERT INTO users (email) VALUES ('same@example.com')"))
    assert runner.rollback() == ["001_users.py"]
    assert not inspect(runner.engine).has_table("users")
    assert history(runner) == []


def test_first_failed_run_rolls_back_schema_and_history_table(runner):
    write_migration(runner, "001_users.py", "users", fail_up=True)
    with pytest.raises(RuntimeError, match="up failed"):
        runner.migrate()
    assert not inspect(runner.engine).has_table("users")
    assert not inspect(runner.engine).has_table("migrations")
    assert _connection.get() is None


def test_failed_batch_rolls_back_all_new_ddl_and_can_retry(runner):
    # Stage 1 deliberately retains v0.1's single transaction per run.
    write_migration(runner, "001_existing.py", "existing")
    runner.migrate()
    write_migration(runner, "002_items.py", "items")
    write_migration(runner, "003_bad.py", "partial", fail_up=True)
    with pytest.raises(RuntimeError, match="up failed"):
        runner.migrate()
    assert inspect(runner.engine).has_table("existing")
    assert not inspect(runner.engine).has_table("items")
    assert not inspect(runner.engine).has_table("partial")
    assert history(runner) == [("001_existing.py", 1)]

    write_migration(runner, "003_bad.py", "partial")
    assert runner.migrate() == ["002_items.py", "003_bad.py"]
    assert history(runner) == [
        ("001_existing.py", 1), ("002_items.py", 2), ("003_bad.py", 2),
    ]
    assert runner.rollback() == ["003_bad.py", "002_items.py"]
    assert history(runner) == [("001_existing.py", 1)]


def test_ddl_error_rolls_back_earlier_changes_in_run(runner):
    # Create history in a committed transaction so it can be inspected after failure.
    runner.migrate()
    write_migration(runner, "001_users.py", "users")
    write_migration(runner, "002_duplicate.py", "users")
    with pytest.raises(DBAPIError):
        runner.migrate()
    assert not inspect(runner.engine).has_table("users")
    assert history(runner) == []
    assert _connection.get() is None


def test_failed_down_restores_dropped_tables_and_history(runner):
    write_migration(runner, "001_first.py", "first", fail_down=True)
    write_migration(runner, "002_second.py", "second")
    runner.migrate()
    with pytest.raises(RuntimeError, match="down failed"):
        runner.rollback()
    assert inspect(runner.engine).has_table("first")
    assert inspect(runner.engine).has_table("second")
    assert history(runner) == [("001_first.py", 1), ("002_second.py", 1)]
    assert _connection.get() is None


def test_missing_file_prevents_partial_rollback(runner):
    first = write_migration(runner, "001_first.py", "first")
    write_migration(runner, "002_second.py", "second")
    runner.migrate()
    first.unlink()
    with pytest.raises(FileNotFoundError, match="001_first.py"):
        runner.rollback()
    assert inspect(runner.engine).has_table("first")
    assert inspect(runner.engine).has_table("second")
    assert len(history(runner)) == 2
