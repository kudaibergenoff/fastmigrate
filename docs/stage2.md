# Stage 2: CLI and migration generator

## Implementation

- Click-based `fastmigrate` entry point, `python -m fastmigrate`, and a copyable
  `manage.py` entry point.
- Process environment configuration (`DATABASE_URL`, `MIGRATIONS_PATH`) with
  explicit command-line overrides. Engine creation is lazy and connections are
  disposed after commands. Generation/help do not require a database URL.
- Timestamped migration generation using exclusive file creation, including
  same-second collision handling and validation of migration names. Table names
  are encoded as Python literals; `--create` emits a runnable create/drop
  migration. `--table` emits an editable, empty scaffold with its target recorded.
- `migrate`, status, last-batch rollback, `rollback --step=N`, reset, refresh and
  fresh. Step counts individual migrations; reset reverses batch order first.
- Existing methods retain their public return types. Runner helpers share a
  single connection so refresh/fresh can be transactional on PostgreSQL. The
  transaction-per-migration/advisory-lock milestone is not folded into this change.
- PostgreSQL bulk DROP TABLE is isolated in `compiler.py`; identifiers are quoted
  by the dialect and CASCADE is never requested. Fresh affects the current schema
  only. External dependencies block the operation instead of being removed.

## Tests

Tests cover generation, valid Python source, collision/concurrent creation,
table-name literal escaping, CLI parsing/configuration/error output, actual
SQLite migration lifecycles, rollback step and reset/refresh/fresh semantics,
entry points and PostgreSQL identifier compilation.

PostgreSQL cases additionally exercise step/reset, atomic refresh/fresh failure,
schema isolation and rejection of dependencies from another schema. These require
`FASTMIGRATE_TEST_DATABASE_URL` and must not be counted as passed when skipped.

## Verification

- Core/generator/compiler suite, excluding the unavailable Click tests:
  **57 passed**. PostgreSQL cases require a separate run (11 cases after this
  milestone's additions).
- CLI tests cannot collect in the current environment: `ModuleNotFoundError:
  No module named 'click'`. They have not passed and must be run after dependency
  installation.
- Python 3.10 grammar parsing/compilation passed for all 19 library/test/manage
  Python files checked.
- Built `dist/fastmigrate-0.1.0-py3-none-any.whl` using a locally cached setuptools
  backend. Verified that it contains the CLI module, its console entry point and
  the Click dependency in wheel metadata. This does not establish successful
  installation or runtime CLI behavior.
- Standard PEP 517 building hit the sandbox's private temporary-directory
  permission issue. The artifact was produced with setuptools' `bdist_wheel`
  command directly, without changing package source or build configuration.
- As in Stage 1, local pytest runs used invocation-local workspace `tmp_path`
  directories to avoid the same Windows sandbox temp permission issue. Test
  assertions and application behavior were not replaced.

To finish verification from the project root in a normal PowerShell terminal:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[postgres,test]"
.\.venv\Scripts\fastmigrate.exe --help
.\.venv\Scripts\python.exe -m pytest -q -m "not postgres"
.\scripts\verify-stage1.ps1 -StartPostgres
```

The final command now exercises the entire suite, including the CLI milestone's
tests, and writes JUnit results under `.tmp`. No package has been published to PyPI.
