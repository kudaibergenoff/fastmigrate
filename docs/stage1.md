# Stage 1: MVP stabilization

## Scope

Preserve the public v0.1 API and its transaction-per-run behavior. CLI commands,
ALTER TABLE, new history columns and advisory locks belong to later stages.

## Changes

- Fixed unique/index modifiers to create SQLAlchemy constraint/index objects
  after the column has been attached to its table. Repeated modifiers are
  idempotent; either order of `unique().index()` produces one unique index.
- Deduplicated dynamically loaded migration classes so an alias of the only
  migration class does not count as a second class.
- Discover files before starting `migrate()`/`status()` transactions, preventing
  history-table creation when the migration directory is missing.
- Kept the existing filename regex: direct checks confirmed it accepts the
  bundled migration and the filenames used in the original tests.
- Added regression tests and six PostgreSQL integration scenarios, using a new
  isolated schema per test. Original test assertions remain unchanged; the
  original engine fixture now disposes its connection pool after each test.
- Added a GitHub Actions workflow with PostgreSQL and Python 3.10/3.13.

## Verification on 2026-10-15

- Python 3.10 grammar parsing and bytecode compilation succeeded for all 12
  project/test Python files (performed with Python 3.13).
- `pyproject.toml` parsed successfully.
- Five direct filename-pattern assertions passed.
- Original and expanded pytest suites **have not executed**: neither pytest nor
  SQLAlchemy is installed in the available Python environments. Installing from
  an index is disabled (`PIP_NO_INDEX=1`); a connection to PyPI was also refused.
- Creating `.venv` produced an interpreter, but pip bootstrap failed on temporary
  directory permissions. It is not a ready-to-use test environment.
- PostgreSQL integration tests **have not executed**: no test URL is configured,
  and access to the Docker API returned `permission denied`.
- The GitHub Actions workflow is prepared but has not been run in this session.

These checks do not establish runtime correctness. Stage 1 acceptance remains
pending until the original tests, new regressions and PostgreSQL suite pass.

## Commands to finish acceptance in a prepared environment

```bash
python -m pip install -e ".[postgres,test]"
python -m pytest -q tests/test_runner.py
python -m pytest -q -m "not postgres"
```

Configure `FASTMIGRATE_TEST_DATABASE_URL` for a dedicated PostgreSQL test database,
then run:

```bash
python -m pytest -q --strict-markers --cov=fastmigrate --cov-report=term-missing --cov-fail-under=80
```

Do not change the original failure test to transaction-per-migration expectations
until that behavior is implemented as a separate runner milestone.
