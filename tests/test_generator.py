import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect

from fastmigrate import MigrationRunner
from fastmigrate.generator import make_migration


def test_plain_template_is_valid_and_discoverable(tmp_path):
    directory = tmp_path / "migrations"
    path = make_migration("create_users_table", directory)
    module = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in module.body if isinstance(node, ast.ClassDef))
    assert cls.name == "CreateUsersTable"
    assert {node.name for node in cls.body if isinstance(node, ast.FunctionDef)} == {"up", "down"}
    engine = create_engine("sqlite://")
    try:
        assert MigrationRunner(engine, directory).migrate() == [path.name]
    finally:
        engine.dispose()


def test_create_template_actually_creates_and_drops_table(tmp_path):
    directory = tmp_path / "migrations"
    path = make_migration("create_users_table", directory, create="users")
    engine = create_engine("sqlite://")
    try:
        runner = MigrationRunner(engine, directory)
        assert runner.migrate() == [path.name]
        assert inspect(engine).get_pk_constraint("users")["constrained_columns"] == ["id"]
        assert runner.rollback() == [path.name]
        assert not inspect(engine).has_table("users")
    finally:
        engine.dispose()


def test_table_template_records_target_without_creating_it(tmp_path):
    path = make_migration("add_phone_to_users", tmp_path, table="users")
    source = path.read_text(encoding="utf-8")
    ast.parse(source)
    assert "table_name = 'users'" in source
    assert "Schema.create" not in source
    assert "Schema.table(self.table_name, change)" in source


def test_table_template_can_execute_against_existing_table(tmp_path):
    engine = create_engine("sqlite://")
    try:
        make_migration("create_users", tmp_path, create="users")
        runner = MigrationRunner(engine, tmp_path)
        runner.migrate()
        path = make_migration("add_phone", tmp_path, table="users")
        assert runner.migrate() == [path.name]
        assert runner.rollback() == [path.name]
        assert inspect(engine).has_table("users")
    finally:
        engine.dispose()


def test_collision_never_overwrites_and_preserves_timestamp_format(tmp_path):
    now = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
    first = make_migration("create_users_table", tmp_path, now=now)
    first.write_text("original content", encoding="utf-8")
    second = make_migration("create_users_table", tmp_path, now=now)
    assert first.name == "2026_10_15_120000_create_users_table.py"
    assert second.name == "2026_10_15_120001_create_users_table.py"
    assert first.read_text(encoding="utf-8") == "original content"


def test_concurrent_generation_uses_exclusive_file_creation(tmp_path):
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(lambda _: make_migration("create_users", tmp_path, now=now), range(8)))
    assert len(set(paths)) == 8
    for path in paths:
        ast.parse(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["../escape", "name.py", "123_name", "", "a-b", "a" * 235])
def test_invalid_name_does_not_create_directory(tmp_path, name):
    directory = tmp_path / "migrations"
    with pytest.raises(ValueError):
        make_migration(name, directory)
    assert not directory.exists()


def test_mutually_exclusive_table_options(tmp_path):
    with pytest.raises(ValueError, match="mutually exclusive"):
        make_migration("change_users", tmp_path, create="users", table="users")


def test_table_names_are_python_literals_not_executable_source(tmp_path):
    target = "users'); raise RuntimeError('injected') #"
    path = make_migration("create_users", tmp_path, create=target)
    ast.parse(path.read_text(encoding="utf-8"))
    engine = create_engine("sqlite://")
    try:
        MigrationRunner(engine, tmp_path).migrate()
        assert inspect(engine).has_table(target)
    finally:
        engine.dispose()
