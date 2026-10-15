import pytest
from sqlalchemy import create_engine, inspect, select, text

from fastmigrate import MigrationRunner
from fastmigrate.generator import make_migration


@pytest.fixture
def runner(tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    engine = create_engine("sqlite://")
    yield MigrationRunner(engine, directory)
    engine.dispose()


def add(runner, name):
    return make_migration("create_" + name, runner.directory, create=name).name


def names(runner):
    with runner.engine.connect() as conn:
        return set(conn.execute(select(runner.history.c.migration)).scalars())


def test_step_counts_migrations_across_batches(runner):
    a = add(runner, "a")
    runner.migrate()
    b = add(runner, "b")
    c = add(runner, "c")
    runner.migrate()
    assert runner.rollback(step=1) == [c]
    assert names(runner) == {a, b}
    assert runner.rollback(step=2) == [b, a]
    assert names(runner) == set()
    assert runner.rollback(step=99) == []


@pytest.mark.parametrize("step", [0, -1, True, 1.5, "2"])
def test_invalid_step_is_rejected_before_database_writes(runner, step):
    with pytest.raises(ValueError, match="positive integer"):
        runner.rollback(step=step)
    assert not inspect(runner.engine).has_table("migrations")


def test_reset_reverses_batches_and_keeps_unmanaged_tables(runner):
    first = add(runner, "z_first")
    runner.migrate()
    second = add(runner, "a_second")
    runner.migrate()
    with runner.engine.begin() as conn:
        conn.execute(text("CREATE TABLE unmanaged (id INTEGER)"))
    assert runner.reset() == [second, first]
    assert names(runner) == set()
    assert inspect(runner.engine).has_table("unmanaged")
    assert runner.reset() == []


@pytest.mark.parametrize("command", ["reset", "refresh"])
def test_all_missing_files_are_checked_before_any_rollback(runner, command):
    first = add(runner, "first")
    runner.migrate()
    add(runner, "second")
    runner.migrate()
    (runner.directory / first).unlink()
    with pytest.raises(FileNotFoundError):
        getattr(runner, command)()
    assert inspect(runner.engine).has_table("second")
    assert len(names(runner)) == 2


def test_refresh_reapplies_and_clears_data(runner):
    first = add(runner, "items")
    runner.migrate()
    second = add(runner, "users")
    with runner.engine.begin() as conn:
        conn.execute(text("INSERT INTO items DEFAULT VALUES"))
    assert runner.refresh() == sorted([first, second])
    assert names(runner) == {first, second}
    with runner.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM items")).scalar_one() == 0


def test_fresh_removes_unmanaged_tables_and_rebuilds(runner):
    first = add(runner, "items")
    runner.migrate()
    with runner.engine.begin() as conn:
        conn.execute(text('CREATE TABLE "external table" (id INTEGER)'))
    assert runner.fresh() == [first]
    assert not inspect(runner.engine).has_table("external table")
    assert inspect(runner.engine).has_table("items")
    assert names(runner) == {first}


def test_fresh_missing_directory_does_not_drop_tables(runner):
    add(runner, "items")
    runner.migrate()
    runner.directory = runner.directory / "missing"
    with pytest.raises(FileNotFoundError):
        runner.fresh()
    assert inspect(runner.engine).has_table("items")
