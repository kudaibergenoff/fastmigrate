# Stages 3–4: Schema Builder and table changes

## Implemented

- All column types from the schema-builder specification, with PostgreSQL as the
  primary dialect and UUID/JSONB variants for SQLite smoke tests.
- `Schema.drop`, `has_table`, `has_column`, `rename` and `table` alongside existing
  create/drop-if-exists operations. The connection remains a ContextVar with
  runner-managed reset.
- Add/drop/rename columns and PostgreSQL type/null/default/comment changes using
  `.change()`. Omitted modifiers preserve existing properties on change.
- Named single/composite indexes and unique constraints; dropping indexes and
  named constraints. Unsigned numeric columns use a named CHECK constraint.
- DDL planning in `compiler.py`: SQLAlchemy quotes identifiers and compiles
  types/defaults/comments. All operations are compiled before execution.
- Deterministic object names with a hash suffix for PostgreSQL's byte limit.
- `--table` generation now emits editable `Schema.table()` callbacks in both
  directions.

## Compatibility change

New column definitions default to NOT NULL. `.nullable()` explicitly permits
NULL and `.nullable(False)` enforces NOT NULL. Existing applied migrations are
not rerun or automatically altered. An author's old migration that relied on
implicit nullability should be made explicit before use on a new database.
The PostgreSQL test migration helper's status column now has an explicit default
because its insert tests deliberately omit that column.

The package retains its 0.1.0 version during development; these changes are
intended for the eventual 0.2.0 release. Foreign-key constraints, advisory locks,
the repository layer and transaction-per-migration are separate remaining stages.

## Verification

- Actual core/builder/generator/runner run: **76 passed, 17 skipped**.
- All 17 skipped cases are PostgreSQL tests: the original 11 plus six new builder
  integrations (types/comments, rename/drop, ALTER/indexes/constraints, changes,
  stored-value casts and failed-ALTER rollback).
- CLI tests were explicitly excluded from this run because Click remains absent.
  Installation was attempted and failed; CLI behavior is still unverified.
- Overall measured coverage is **76%**, including the unexecuted CLI module.
  Schema coverage is **100%**, Blueprint **95%**, Compiler **94%**. The full
  project's 80% gate has not been established by this partial run.
- As documented in Stage 1, the successful pytest invocation used fresh workspace
  directories for `tmp_path` to avoid the Windows sandbox's private-directory
  permission issue. Test assertions and application behavior were unchanged.
- JUnit report: `.tmp/stage3-results.xml` (ignored by Git).
- Rebuilt `dist/fastmigrate-0.1.0-py3-none-any.whl` with the current source and
  package README metadata. Imported the wheel directly in an isolated Python
  process and successfully executed create/add-column/has-column against SQLite.
  This verifies the artifact contents; pip installation and CLI execution still
  require Click. Syntax/compilation checks passed for 24 Python files.

## Run the complete suite in a prepared environment

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[postgres,test]"
.\scripts\verify-stage1.ps1 -StartPostgres
```

Despite its historical name, this script runs all current tests and writes their
JUnit reports. PostgreSQL tests create only isolated test schemas. No migration
or destructive command has been executed against a user application database.
