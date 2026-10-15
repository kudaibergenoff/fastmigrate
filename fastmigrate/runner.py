from pathlib import Path
import hashlib
import importlib.util
import re
import sys
from sqlalchemy import MetaData, Table, Column, String, Integer, select, func, insert, delete, inspect
from .compiler import DropTables
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
        with self.engine.begin() as conn:
            return self._apply(conn, files)

    def _apply(self, conn, files):
        applied = []
        self.history.create(conn, checkfirst=True)
        existing = set(conn.execute(select(self.history.c.migration)).scalars())
        batch = (conn.execute(select(func.max(self.history.c.batch))).scalar() or 0) + 1
        token = _connection.set(conn)
        try:
            for path in files:
                if path.name in existing:
                    continue
                self._load(path).up()
                conn.execute(insert(self.history).values(migration=path.name, batch=batch))
                applied.append(path.name)
        finally:
            _connection.reset(token)
        return applied

    def _history_names(self):
        return select(self.history.c.migration).order_by(
            self.history.c.batch.desc(), self.history.c.migration.desc()
        )

    def _revert(self, conn, names, files):
        paths = {p.name: p for p in files}
        missing = set(names) - paths.keys()
        if missing:
            raise FileNotFoundError(f"Missing migration files: {sorted(missing)}")
        token = _connection.set(conn)
        try:
            for name in names:
                self._load(paths[name]).down()
                conn.execute(delete(self.history).where(self.history.c.migration == name))
        finally:
            _connection.reset(token)
        return names

    def rollback(self, step=None):
        """Reverse the last batch, or the last N migrations when step is set."""
        if step is not None and (type(step) is not int or step <= 0):
            raise ValueError("step must be a positive integer")
        with self.engine.begin() as conn:
            self.history.create(conn, checkfirst=True)
            query = self._history_names()
            if step is None:
                batch = conn.execute(select(func.max(self.history.c.batch))).scalar()
                query = query.where(self.history.c.batch == batch)
            else:
                query = query.limit(step)
            names = list(conn.execute(query).scalars())
            if not names:
                return []
            return self._revert(conn, names, self._files())

    def reset(self):
        """Reverse every applied migration, most recent batch first."""
        files = self._files()
        with self.engine.begin() as conn:
            self.history.create(conn, checkfirst=True)
            names = list(conn.execute(self._history_names()).scalars())
            return self._revert(conn, names, files)

    def refresh(self):
        """Reset and reapply in one transaction (transactional DDL on PostgreSQL)."""
        files = self._files()
        with self.engine.begin() as conn:
            self.history.create(conn, checkfirst=True)
            names = list(conn.execute(self._history_names()).scalars())
            self._revert(conn, names, files)
            return self._apply(conn, files)

    def fresh(self):
        """Drop ALL tables in the current schema, then apply migrations."""
        files = self._files()
        dialect = self.engine.dialect.name
        if dialect not in {"postgresql", "sqlite"}:
            raise NotImplementedError("fresh supports PostgreSQL and SQLite only")
        with self.engine.begin() as conn:
            if dialect == "postgresql":
                schema = conn.execute(select(func.current_schema())).scalar_one()
                if not schema or schema.startswith("pg_") or schema == "information_schema":
                    raise ValueError("fresh requires a non-system current schema")
                metadata = MetaData()
                tables = [
                    Table(name, metadata, schema=schema)
                    for name in inspect(conn).get_table_names(schema=schema)
                ]
                if tables:
                    # One DROP handles mutual dependencies within the selected set.
                    # No CASCADE: external dependencies fail instead of being removed.
                    conn.execute(DropTables(tables))
            else:
                metadata = MetaData()
                metadata.reflect(conn)
                metadata.drop_all(conn)
            return self._apply(conn, files)

    def status(self):
        files = self._files()
        with self.engine.begin() as conn:
            self.history.create(conn, checkfirst=True)
            applied = set(conn.execute(select(self.history.c.migration)).scalars())
            return [(p.name, p.name in applied) for p in files]
