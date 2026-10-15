from pathlib import Path
import hashlib
import importlib.util
import re
import sys
from sqlalchemy import MetaData, Table, Column, String, Integer, select, func, insert, delete
from .migration import Migration
from .schema import _connection

FILE_PATTERN = re.compile(r"^[a-zA-Z0-9_]+\.py$")

class MigrationRunner:
    def __init__(self, engine, migrations_dir):
        self.engine = engine
        self.directory = Path(migrations_dir)
        self.history = Table(
            "migrations", MetaData(),
            Column("migration", String(255), primary_key=True),
            Column("batch", Integer, nullable=False),
        )

    def _files(self):
        if not self.directory.is_dir():
            raise FileNotFoundError(self.directory)
        return sorted(
            p for p in self.directory.iterdir()
            if p.is_file() and p.name != "__init__.py" and FILE_PATTERN.fullmatch(p.name)
        )

    def _load(self, path):
        module_name = "fastmigrate_user_" + hashlib.sha256(str(path.resolve()).encode()).hexdigest()
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load migration: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            candidates = {
                value for value in vars(module).values()
                if isinstance(value, type)
                and issubclass(value, Migration)
                and value is not Migration
                and value.__module__ == module_name
            }
            if len(candidates) != 1:
                raise ValueError(f"{path.name} must define exactly one Migration subclass")
            return next(iter(candidates))()
        finally:
            sys.modules.pop(module_name, None)

    def migrate(self):
        files = self._files()
        applied = []
        # One transaction for this run: schema + history commit together.
        with self.engine.begin() as conn:
            self.history.create(conn, checkfirst=True)
            existing = set(conn.execute(select(self.history.c.migration)).scalars())
            batch = (conn.execute(select(func.max(self.history.c.batch))).scalar() or 0) + 1
            token = _connection.set(conn)
            try:
                for path in files:
                    if path.name in existing:
                        continue
                    migration = self._load(path)
                    migration.up()
                    conn.execute(insert(self.history).values(migration=path.name, batch=batch))
                    applied.append(path.name)
            finally:
                _connection.reset(token)
        return applied

    def rollback(self):
        rolled_back = []
        with self.engine.begin() as conn:
            self.history.create(conn, checkfirst=True)
            batch = conn.execute(select(func.max(self.history.c.batch))).scalar()
            if batch is None:
                return rolled_back
            names = list(conn.execute(
                select(self.history.c.migration)
                .where(self.history.c.batch == batch)
                .order_by(self.history.c.migration.desc())
            ).scalars())
            paths = {p.name: p for p in self._files()}
            missing = set(names) - paths.keys()
            if missing:
                raise FileNotFoundError(f"Missing migration files: {sorted(missing)}")
            token = _connection.set(conn)
            try:
                for name in names:
                    self._load(paths[name]).down()
                    conn.execute(delete(self.history).where(self.history.c.migration == name))
                    rolled_back.append(name)
            finally:
                _connection.reset(token)
        return rolled_back

    def status(self):
        files = self._files()
        with self.engine.begin() as conn:
            self.history.create(conn, checkfirst=True)
            applied = set(conn.execute(select(self.history.c.migration)).scalars())
            return [(p.name, p.name in applied) for p in files]
