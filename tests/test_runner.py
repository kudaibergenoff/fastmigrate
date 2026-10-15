from pathlib import Path
import pytest
from sqlalchemy import create_engine, inspect, text
from fastmigrate import MigrationRunner

MIGRATION = """
from fastmigrate import Migration, Schema

class CreateItems(Migration):
    def up(self):
        Schema.create("items", lambda t: (
            t.id(), t.string("name").unique(), t.boolean("enabled").default(True)
        ))
    def down(self):
        Schema.drop_if_exists("items")
"""

@pytest.fixture
def setup(tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "001_create_items.py").write_text(MIGRATION)
    engine = create_engine("sqlite+pysqlite:///" + str(tmp_path / "test.db"))
    yield engine, directory, MigrationRunner(engine, directory)
    engine.dispose()

def test_migrate_idempotent_and_rollback(setup):
    engine, _, runner = setup
    assert runner.migrate() == ["001_create_items.py"]
    assert runner.migrate() == []
    assert inspect(engine).has_table("items")
    assert runner.status() == [("001_create_items.py", True)]
    with engine.connect() as conn:
        conn.execute(text("INSERT INTO items (name) VALUES ('first')"))
        assert conn.execute(text("SELECT enabled FROM items")).scalar() == 1
    assert runner.rollback() == ["001_create_items.py"]
    assert not inspect(engine).has_table("items")
    assert runner.rollback() == []

def test_failed_migration_does_not_record_history(setup):
    engine, directory, runner = setup
    (directory / "002_bad.py").write_text("""
from fastmigrate import Migration
class Bad(Migration):
    def up(self):
        raise RuntimeError("boom")
    def down(self):
        pass
""")
    with pytest.raises(RuntimeError, match="boom"):
        runner.migrate()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM migrations")).scalar() == 0

def test_missing_file_blocks_rollback(setup):
    engine, directory, runner = setup
    runner.migrate()
    (directory / "001_create_items.py").unlink()
    with pytest.raises(FileNotFoundError):
        runner.rollback()
