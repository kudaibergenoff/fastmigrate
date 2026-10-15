import hashlib
import sys

import pytest
from sqlalchemy import create_engine, inspect, select

from fastmigrate import MigrationRunner, Schema
from fastmigrate.schema import _connection


@pytest.fixture
def runner(tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    yield MigrationRunner(engine, directory)
    engine.dispose()


def write_migration(directory, filename, table, *, up_extra="", down_extra=""):
    path = directory / filename
    path.write_text(
        "from fastmigrate import Migration, Schema\n"
        "class Change(Migration):\n"
        "    def up(self):\n"
        f"        Schema.create({table!r}, lambda t: t.id())\n"
        f"{up_extra}"
        "    def down(self):\n"
        f"        Schema.drop_if_exists({table!r})\n"
        f"{down_extra}",
        encoding="utf-8",
    )
    return path


def history(runner):
    with runner.engine.connect() as conn:
        return conn.execute(
            select(runner.history).order_by(runner.history.c.migration)
        ).all()


def test_discovery_filters_and_sorts_files(runner):
    for name in ("002_second.py", "001_first.py", "2026_10_13_120000_create_users_table.py"):
        write_migration(runner.directory, name, "table_" + name.split("_")[0])
    for name in ("__init__.py", "notes.txt", "invalid-name.py", "001_first.py.bak"):
        (runner.directory / name).write_text("raise RuntimeError('must not load')", encoding="utf-8")
    (runner.directory / "003_directory.py").mkdir()
    assert runner.status() == [
        ("001_first.py", False),
        ("002_second.py", False),
        ("2026_10_13_120000_create_users_table.py", False),
    ]
    assert runner.migrate() == [name for name, _ in runner.status()]
    assert all(applied for _, applied in runner.status())


def test_empty_directory(runner):
    assert runner.migrate() == []
    assert runner.status() == []
    assert runner.rollback() == []
    assert history(runner) == []


def test_missing_directory_does_not_create_history(runner):
    runner.directory = runner.directory / "missing"
    with pytest.raises(FileNotFoundError):
        runner.migrate()
    assert not inspect(runner.engine).has_table("migrations")


def test_batch_numbers_idempotence_and_reverse_rollback_order(runner):
    write_migration(runner.directory, "001_first.py", "first")
    assert runner.migrate() == ["001_first.py"]
    assert runner.migrate() == []
    write_migration(runner.directory, "003_third.py", "third")
    write_migration(runner.directory, "002_second.py", "second")
    assert runner.migrate() == ["002_second.py", "003_third.py"]
    assert history(runner) == [
        ("001_first.py", 1), ("002_second.py", 2), ("003_third.py", 2),
    ]
    assert runner.rollback() == ["003_third.py", "002_second.py"]
    assert history(runner) == [("001_first.py", 1)]
    assert inspect(runner.engine).has_table("first")
    assert not inspect(runner.engine).has_table("second")
    assert not inspect(runner.engine).has_table("third")


def test_missing_file_is_checked_before_any_down(runner):
    first = write_migration(runner.directory, "001_first.py", "first")
    write_migration(runner.directory, "002_second.py", "second")
    runner.migrate()
    first.unlink()
    with pytest.raises(FileNotFoundError, match="001_first.py"):
        runner.rollback()
    assert inspect(runner.engine).has_table("second")
    assert len(history(runner)) == 2


@pytest.mark.parametrize("source,error,match", [
    ("from fastmigrate import Migration\n", ValueError, "exactly one"),
    (
        "from fastmigrate import Migration\n"
        "class A(Migration):\n"
        "    def up(self): pass\n"
        "    def down(self): pass\n"
        "class B(A): pass\n",
        ValueError, "exactly one",
    ),
    (
        "from fastmigrate import Migration\n"
        "class Incomplete(Migration):\n"
        "    def up(self): pass\n",
        TypeError, "abstract",
    ),
    ("raise RuntimeError('import failed')\n", RuntimeError, "import failed"),
    ("class Broken(:\n", SyntaxError, None),
])
def test_invalid_modules_fail_without_history_or_context_leaks(runner, source, error, match):
    path = runner.directory / "001_invalid.py"
    path.write_text(source, encoding="utf-8")
    module_name = "fastmigrate_user_" + hashlib.sha256(str(path.resolve()).encode()).hexdigest()
    with pytest.raises(error, match=match):
        runner.migrate()
    assert history(runner) == []
    assert _connection.get() is None
    assert module_name not in sys.modules


def test_alias_of_migration_class_is_not_a_second_class(runner):
    path = write_migration(runner.directory, "001_alias.py", "items")
    with path.open("a", encoding="utf-8") as stream:
        stream.write("Alias = Change\n")
    assert runner.migrate() == [path.name]
    assert inspect(runner.engine).has_table("items")


@pytest.mark.parametrize("operation", ["migrate", "rollback"])
@pytest.mark.parametrize("fail", [False, True])
def test_context_restores_previous_value(runner, operation, fail):
    up_body = 'raise RuntimeError("up failed")' if fail and operation == "migrate" else "pass"
    down_body = 'raise RuntimeError("down failed")' if fail and operation == "rollback" else "pass"
    source = (
        "from fastmigrate import Migration\n"
        "class Change(Migration):\n"
        f"    def up(self): {up_body}\n"
        f"    def down(self): {down_body}\n"
    )
    (runner.directory / "001_context.py").write_text(source, encoding="utf-8")
    if operation == "rollback":
        runner.migrate()
    previous = object()
    token = _connection.set(previous)
    try:
        if fail:
            with pytest.raises(RuntimeError, match="failed"):
                getattr(runner, operation)()
        else:
            getattr(runner, operation)()
        assert _connection.get() is previous
    finally:
        _connection.reset(token)


def test_schema_requires_active_runner():
    with pytest.raises(RuntimeError, match="active MigrationRunner"):
        Schema.create("items", lambda t: t.id())
    with pytest.raises(RuntimeError, match="active MigrationRunner"):
        Schema.drop_if_exists("items")
