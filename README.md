# FastMigrate — stage 1

A Laravel-inspired migration API built on SQLAlchemy Core.

## Install and test

```bash
pip install -e ".[test]"
pytest -q
```

The test suite includes regression checks for migration discovery/loading, batches,
connection-context cleanup, indexes and unique constraints. PostgreSQL tests are
skipped unless a dedicated test database is explicitly configured. A passing
SQLite run alone does not verify PostgreSQL DDL rollback.

### PostgreSQL integration tests

Install the PostgreSQL driver and test dependencies:

```bash
pip install -e ".[postgres,test]"
```

Set `FASTMIGRATE_TEST_DATABASE_URL` to a **dedicated test database** using the
`postgresql+psycopg://` driver. For example, in PowerShell:

```powershell
$env:FASTMIGRATE_TEST_DATABASE_URL = "postgresql+psycopg://postgres:password@localhost:5432/fastmigrate_test"
python -m pytest -q -m postgres
```

Each test creates a unique `fastmigrate_test_<uuid>` schema and removes only that
schema afterwards. The database user needs permission to create schemas. The
fixture never reads `DATABASE_URL`. If the test URL is set but the database is
unreachable, the tests fail rather than silently skipping.

Run all checks, including coverage:

```bash
python -m pytest -q --strict-markers --cov=fastmigrate --cov-report=term-missing
```

GitHub Actions runs this suite on Python 3.10 and 3.13 with a PostgreSQL 17 service.
The workflow must actually run successfully before its results can be claimed.

## Demo

```bash
python example.py migrate
python example.py status
python example.py rollback
```

Set `DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/dbname` for PostgreSQL and install `pip install -e ".[postgres,test]"`.

## Stage 1 scope

`Schema.create`, `Schema.drop_if_exists`, `Blueprint` basic types,
database-side defaults, indexes, unique constraints, timestamps,
migration history, batch rollback and status.

**Limitations:** SQLite is for smoke tests; SQLite DDL rollback is not guaranteed.
PostgreSQL supports transactional DDL, but the runner does not yet implement
cross-process advisory locks. No `Schema.table`, foreign keys, CLI generator,
async runner, `fresh`, or production-safe concurrent migrations yet.
Migration filenames must be trusted Python code. Do not run untrusted migration files.

### Stage 1 behavior

- Migration filenames may contain ASCII letters, digits and underscores, followed
  by `.py`. `__init__.py` is ignored; files are executed in filename order.
- A file must define exactly one `Migration` subclass. An alias of that same class
  is allowed; imported migration classes are not selected.
- A missing migration directory is rejected before `migrate()` or `status()`
  starts a database transaction.
- `.unique()` creates a unique constraint; `.index()` creates an index. Chaining
  both creates one unique index regardless of modifier order.
- Stage 1 preserves the v0.1 transaction model: **one transaction per run**,
  including schema operations and history writes. On PostgreSQL, a failed run
  rolls back all migrations from that run, including history-table creation if
  this was the first run. Previously committed batches remain unchanged.
- `rollback()` reverses the last batch in reverse filename order. All required
  files are checked before the first `down()` runs.

The v0.2 transaction-per-migration model and advisory locking are a subsequent
runner milestone. Ordinary columns still allow NULL by default in v0.1;
`.nullable()` explicitly permits it. `timestamps()` supplies insert defaults,
but does not automatically update `updated_at`. `status()` currently creates the
history table if needed and lists only files present in the migration directory.

See [Stage 1 verification notes](docs/stage1.md) for the local verification status.
