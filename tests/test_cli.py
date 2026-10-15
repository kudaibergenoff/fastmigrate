import ast
from pathlib import Path
import subprocess
import sys

from click.testing import CliRunner
import pytest
from sqlalchemy import create_engine, inspect, text

from fastmigrate.cli import cli


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MIGRATIONS_PATH", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///" + str(tmp_path / "test.db"))
    monkeypatch.setenv("MIGRATIONS_PATH", str(tmp_path / "migrations"))
    return CliRunner(), tmp_path


def invoke(runner, args, **kwargs):
    result = runner.invoke(cli, args, **kwargs)
    assert result.exit_code == 0, result.output
    return result.output


def test_help_and_generator_do_not_require_database(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MIGRATIONS_PATH", raising=False)
    runner = CliRunner()
    output = invoke(runner, ["--help"])
    for command in ("make:migration", "migrate:status", "migrate:rollback", "migrate:reset", "migrate:refresh", "migrate:fresh"):
        assert command in output
    directory = tmp_path / "migrations"
    invoke(runner, ["--migrations-path", str(directory), "make:migration", "create_users", "--create=users"])
    path, = directory.glob("*.py")
    ast.parse(path.read_text(encoding="utf-8"))


def test_cli_full_lifecycle(project):
    runner, path = project
    invoke(runner, ["make:migration", "create_users", "--create=users"])
    assert "Pending" in invoke(runner, ["migrate:status"])
    assert "Applied" in invoke(runner, ["migrate"])
    assert "Applied" in invoke(runner, ["migrate:status"])
    assert "Nothing to migrate" in invoke(runner, ["migrate"])
    assert "Rolled back" in invoke(runner, ["migrate:rollback"])
    assert "Nothing to rollback" in invoke(runner, ["migrate:rollback"])
    engine = create_engine("sqlite:///" + str(path / "test.db"))
    try:
        assert not inspect(engine).has_table("users")
    finally:
        engine.dispose()


def test_step_reset_and_refresh(project):
    runner, _ = project
    invoke(runner, ["make:migration", "create_a", "--create=a"])
    invoke(runner, ["migrate"])
    invoke(runner, ["make:migration", "create_b", "--create=b"])
    invoke(runner, ["migrate"])
    assert invoke(runner, ["migrate:rollback", "--step=1"]).count("Rolled back") == 1
    assert invoke(runner, ["migrate:refresh"]).count("Applied") == 2
    assert invoke(runner, ["migrate:reset"]).count("Rolled back") == 2


def test_fresh_confirmation_and_force(project):
    runner, path = project
    invoke(runner, ["make:migration", "create_users", "--create=users"])
    invoke(runner, ["migrate"])
    engine = create_engine("sqlite:///" + str(path / "test.db"))
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE unmanaged (id INTEGER)"))
        result = runner.invoke(cli, ["migrate:fresh"], input="n\n")
        assert result.exit_code != 0
        assert inspect(engine).has_table("unmanaged")
        assert "Applied" in invoke(runner, ["migrate:fresh", "--force"])
        assert not inspect(engine).has_table("unmanaged")
        assert inspect(engine).has_table("users")
    finally:
        engine.dispose()


def test_table_generation_is_an_editable_scaffold(project):
    runner, path = project
    output = invoke(runner, ["make:migration", "add_phone", "--table=users"])
    source = next((path / "migrations").glob("*.py")).read_text(encoding="utf-8")
    assert "table_name = 'users'" in source
    assert "editable" in output


@pytest.mark.parametrize("args,expected", [
    (["make:migration", "../escape"], "snake_case"),
    (["make:migration", "change", "--create=users", "--table=users"], "mutually exclusive"),
    (["migrate:rollback", "--step=0"], "range"),
    (["migrate:rollback", "--step=-1"], "range"),
    (["migrate:rollback", "--step=no"], "integer"),
    (["unknown"], "No such command"),
    (["migrate"], "migrations"),
])
def test_errors_have_nonzero_exit_without_traceback(project, args, expected):
    runner, _ = project
    result = runner.invoke(cli, args)
    assert result.exit_code != 0
    assert expected.lower() in result.output.lower()
    assert "Traceback" not in result.output


def test_missing_database_url_is_explicit(project, monkeypatch):
    runner, _ = project
    monkeypatch.delenv("DATABASE_URL")
    result = runner.invoke(cli, ["migrate"])
    assert result.exit_code != 0
    assert "DATABASE_URL" in result.output


def test_explicit_configuration_overrides_environment(project):
    runner, path = project
    directory = path / "custom"
    options = ["--database-url", "sqlite:///" + str(path / "override.db"), "--migrations-path", str(directory)]
    invoke(runner, options + ["make:migration", "create_users", "--create=users"])
    invoke(runner, options + ["migrate"])
    assert (path / "override.db").exists()
    assert not (path / "test.db").exists()


def test_migration_failure_is_reported(project):
    runner, path = project
    invoke(runner, ["make:migration", "broken"])
    migration = next((path / "migrations").glob("*.py"))
    migration.write_text("raise RuntimeError('broken migration')", encoding="utf-8")
    result = runner.invoke(cli, ["migrate"])
    assert result.exit_code == 1
    assert "broken migration" in result.output


def test_driver_error_does_not_print_database_password(project):
    runner, _ = project
    result = runner.invoke(cli, ["--database-url", "missingdriver://user:do_not_print@localhost/db", "migrate"])
    assert result.exit_code == 1
    assert "do_not_print" not in result.output


@pytest.mark.parametrize("entry", [["-m", "fastmigrate"], [str(Path(__file__).resolve().parents[1] / "manage.py")]])
def test_python_entrypoints(entry):
    result = subprocess.run([sys.executable, *entry, "--help"], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert "make:migration" in result.stdout
