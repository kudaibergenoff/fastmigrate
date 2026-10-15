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

After the user prepared the environment, `.venv` contains pytest, pytest-cov,
SQLAlchemy and psycopg. Actual results with Python 3.13.7:

- Original suite (`tests/test_runner.py`): **3 passed**.
- Complete collected suite: **31 passed, 6 skipped**.
- Coverage: **99.39%** (163 of 164 statements); Blueprint and Schema: **100%**.
- The six skipped cases are all PostgreSQL integration tests. No
  `FASTMIGRATE_TEST_DATABASE_URL` is configured in the agent's process; Docker
  API access is denied, and a connection to the test endpoint on port 55432
  timed out. PostgreSQL acceptance is still pending a successful test report.
- JUnit output from this run: `.tmp/stage1-results.xml` (ignored by Git).
- Python 3.10 grammar parsing and compilation previously succeeded for all 12
  project/test Python files; `pyproject.toml` and five filename-pattern checks
  also passed.
- The GitHub Actions workflow has not been run in this session.

The first standard pytest invocation failed during fixture setup because this
Windows sandbox cannot access directories created by pytest with private temp
permissions. The successful runs used an invocation-local pytest plugin replacing
only `tmp_path`: each test received a fresh UUID directory under `.tmp`, created
with inherited workspace permissions. The built-in temp plugin and cache were
disabled. No test assertions, migrations or application behavior were replaced.
This workaround is not installed in the project or used by the normal CI suite.

Stage 1's unit/regression verification is complete. Full acceptance still requires
the six PostgreSQL integration tests to pass.

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

## Follow-up: reproducible local acceptance

Initially, dependencies were absent and no suitable SQLAlchemy/pytest wheels
were found in the local pip HTTP cache. The user subsequently prepared `.venv`;
the results above supersede that initial dependency blocker.

Added `scripts/verify-stage1.ps1` and `compose.test.yaml` so acceptance can be run
from a normal PowerShell terminal:

```powershell
.\scripts\verify-stage1.ps1 -StartPostgres
```

The script creates its own uniquely named Compose project and only removes that
project's test container. PostgreSQL listens on loopback and stores data in tmpfs.
An offline wheel directory can be supplied with `-Wheelhouse`; `-UnitOnly` is an
explicit partial-verification mode. Failure to prepare dependencies or connect
to Docker stops execution rather than reporting tests as passed.

Verification of the helper: PowerShell parsing and `docker compose --file
compose.test.yaml config --quiet` succeeded. Running the helper with
`-StartPostgres` stopped at the Docker permission check, before creating a
container. Original/regression tests have now passed; PostgreSQL acceptance
remains pending.
