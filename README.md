# FastMigrate

A Laravel-inspired migration API built on SQLAlchemy Core.

FastMigrate is a standalone Python package. It does not require FastAPI, an ORM,
or Alembic. The CLI milestone adds generation and migration commands; the
complete v0.2 schema builder and production concurrency protection are still
under development. The distribution version remains 0.1.0 until release readiness.

## Use in a Python project

During development, install this checkout (or its absolute path) into your
project's virtual environment:

```bash
python -m pip install -e ".[postgres]"
fastmigrate --help
```

The intended published installation is `pip install fastmigrate[postgres]`.
Publication of this checkout to PyPI has not been performed. The base package
includes SQLAlchemy and Click; `[postgres]` adds psycopg 3.

Configure environment variables in PowerShell:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://user:password@localhost:5432/app"
$env:MIGRATIONS_PATH = "./migrations"
fastmigrate make:migration create_users_table --create=users
fastmigrate migrate
fastmigrate migrate:status
fastmigrate migrate:rollback
```

On Linux/macOS use `export DATABASE_URL=...` and `export MIGRATIONS_PATH=...`.
Variables are read from the process environment; `.env` files are not loaded
automatically. Alternatively, pass options **before** the command:

```bash
fastmigrate --database-url "sqlite:///demo.db" --migrations-path ./migrations migrate
```

No database URL is required for `--help`, `--version`, or `make:migration`.

## CLI commands

| Command | Behavior |
| --- | --- |
| `make:migration NAME` | Create an editable migration with `up()` and `down()` |
| `make:migration NAME --create=users` | Create a working create/drop template with an `id` column |
| `make:migration NAME --table=users` | Create an editable scaffold with `table_name = 'users'` |
| `migrate` | Apply pending migrations in filename order |
| `migrate:status` | List discovered files as Applied/Pending |
| `migrate:rollback` | Reverse the most recent batch |
| `migrate:rollback --step=2` | Reverse the last two migrations, even across batches |
| `migrate:reset` | Reverse all applied migrations, most recent batch first |
| `migrate:refresh` | Reset and apply all current migration files |
| `migrate:fresh` | Drop all tables in the current schema and apply migrations |

Names must be snake_case and start with a letter. Filenames use UTC timestamps,
for example `2026_10_15_120000_create_users_table.py`. Existing files are never
overwritten: a same-name collision advances the timestamp by one second.
`--create` and `--table` cannot be combined. Edit empty scaffolds before applying
them: the `--table` option records the target but does not infer column changes.
The `--table` template calls `Schema.table()` in both directions; fill in its
callbacks with the forward and reverse changes.

`reset` and `refresh` execute user-defined `down()` methods and may delete data.
`fresh` additionally removes tables not managed by migration history. It requires
interactive confirmation, or `--force` for an explicitly requested noninteractive
run. PostgreSQL `fresh` targets only `current_schema()`, never uses `CASCADE`, and
fails if outside objects depend on those tables. Views, standalone sequences and
other non-table objects are not removed. SQLite operates on its main database.

The current runner retains one transaction per command. On PostgreSQL a failed
`refresh`/`fresh` restores the prior schema, data and history. SQLite is only a
smoke-test backend and does not guarantee DDL rollback. Advisory locking and the
v0.2 transaction-per-migration model are later milestones.

The same CLI can be invoked with:

```bash
python -m fastmigrate migrate
python manage.py migrate
```

Copy the supplied `manage.py` into your consuming project's root, or create it:

```python
from fastmigrate.cli import cli

if __name__ == "__main__":
    cli()
```

Command errors return nonzero exit codes and concise diagnostics. Application
code can continue using `MigrationRunner(engine, migrations_dir)` directly;
`rollback()` retains its original last-batch behavior.

## Schema Builder

Schema operations use the active migration connection. For example:

```python
from fastmigrate import Migration, Schema


class CreateUsersTable(Migration):
    def up(self):
        Schema.create("users", lambda table: (
            table.id(),
            table.uuid("public_id").unique(),
            table.string("email").unique(),
            table.integer("age").unsigned(),
            table.boolean("active").default(True),
            table.jsonb("preferences").nullable(),
            table.timestamps(),
            table.soft_deletes(),
        ))

    def down(self):
        Schema.drop_if_exists("users")
```

Public methods: `Schema.create`, `Schema.table`, `Schema.drop`,
`Schema.drop_if_exists`, `Schema.has_table`, `Schema.has_column` and
`Schema.rename`. They require an active `MigrationRunner` and share its connection.
`Schema.rename("users", "customers")` renames within the current schema.

| Column method | PostgreSQL type |
| --- | --- |
| `id(name="id")` | BIGSERIAL primary key |
| `uuid(name)` | UUID (Python `uuid.UUID` values) |
| `string(name, length=255)` | VARCHAR |
| `text(name)` | TEXT |
| `integer(name)` / `big_integer(name)` / `small_integer(name)` | INTEGER / BIGINT / SMALLINT |
| `boolean(name)` | BOOLEAN |
| `decimal(name, precision=8, scale=2)` | NUMERIC |
| `float(name, precision=None)` | FLOAT |
| `date(name)` | DATE |
| `date_time(name, timezone=False)` | TIMESTAMP without timezone by default |
| `timestamp(name, timezone=True)` | TIMESTAMP with timezone by default |
| `json(name)` / `jsonb(name)` | JSON / JSONB |
| `binary(name)` | BYTEA |
| `foreign_id(name)` | BIGINT; foreign-key constraints are a subsequent milestone |
| `timestamps()` | created_at, updated_at with insert defaults |
| `soft_deletes(name="deleted_at")` | nullable timestamp |

**Behavior change for v0.2 development:** ordinary columns now use `NOT NULL` by
default. Call `.nullable()` explicitly to allow NULL, or `.nullable(False)` to
require a value. This affects newly executed DDL; existing tables are not changed
automatically. `soft_deletes()` is nullable. `timestamps()` supplies insert
defaults and does not automatically update `updated_at`.

Column modifiers include `.default(value)`, `.unique()`, `.index()`,
`.unsigned()` and `.comment(text)`. Defaults accept string, boolean, integer and
float literals. PostgreSQL unsigned values are enforced by a named `CHECK
(column >= 0)` constraint, not an unsupported unsigned SQL type.

## Changing tables

```python
class AddPhoneToUsers(Migration):
    def up(self):
        Schema.table("users", lambda table: (
            table.string("phone").nullable(),
            table.boolean("verified").default(False),
        ))

    def down(self):
        Schema.table("users", lambda table: (
            table.drop_column("phone"),
            table.drop_column("verified"),
        ))
```

Inside `Schema.table()`:

```python
table.rename_column("phone", "mobile")
table.string("name", 100).nullable(False).change()
table.big_integer("age").drop_default().change()
table.index(["email", "name"], "users_lookup")
table.unique(["public_id", "email"], "users_identity_unique")
table.drop_index("users_lookup")
table.drop_constraint("users_identity_unique")  # drop_unique(name) is an alias
```

`.change()` updates the declared type. Explicit nullable/default/comment
modifiers update those properties; omitted modifiers preserve existing values.
Type changes use a dialect-compiled `CAST` of the quoted column. Incompatible
stored data or defaults cause a database error and PostgreSQL transaction
rollback. Raw USING SQL is not accepted by this API.

Column operations run in callback order; added constraints and indexes follow.
All DDL is compiled before execution. Identifiers, defaults and comments are
escaped through SQLAlchemy. Generated object names use
`<table>_<columns>_index`, `_unique` or `_unsigned`; long names receive a stable
hash suffix to fit PostgreSQL's 63-byte identifier limit. `.unique().index()`
creates a unique index, which is removed with `drop_index()`.

SQLite smoke tests support create/drop/rename, adding/dropping/renaming columns
and indexes. Existing-column type changes, constraint changes and ALTER comments
require PostgreSQL. JSONB uses SQLite JSON in smoke tests. Unsupported ALTER
operations are rejected before any DDL in that callback is executed.

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

### Windows: verify Stage 1 in one command

From a PowerShell terminal with Python 3.10+, working package access and Docker
Desktop running Linux containers:

```powershell
.\scripts\verify-stage1.ps1 -StartPostgres
```

The script prepares `.venv`, installs the package with test dependencies, runs the
three original tests and then the full suite with coverage. It starts a uniquely
named PostgreSQL test project on `127.0.0.1:55432`, uses temporary database storage,
and removes its own container in `finally`. Pass `-PostgresPort 55433` if the port
is occupied. No existing database is used in this mode.
JUnit reports are saved to `.tmp/stage1-original.xml` and
`.tmp/stage1-results.xml` so the results can be reviewed after the container exits.

With `FASTMIGRATE_TEST_DATABASE_URL` already configured, run the script without
`-StartPostgres`. To run only the unit/SQLite regressions:

```powershell
.\scripts\verify-stage1.ps1 -UnitOnly
```

For an offline environment, supply `-Wheelhouse C:\wheels`. The directory must
contain compatible wheels for the selected extras, their dependencies and the
build backend (`setuptools>=68`). The script respects existing pip settings,
including `PIP_NO_INDEX`; it does not change system proxy or index configuration.
`-UnitOnly` is partial verification and does not complete PostgreSQL acceptance.

## Demo

```bash
python example.py migrate
python example.py status
python example.py rollback
```

Set `DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/dbname` for PostgreSQL and install `pip install -e ".[postgres,test]"`.

## Current scope and limitations

Schema creation and alteration, PostgreSQL column types, database defaults,
indexes, unique/CHECK constraints, CLI generation, migration history and rollback.

**Limitations:** SQLite is for smoke tests; SQLite DDL rollback is not guaranteed.
PostgreSQL supports transactional DDL, but the runner does not yet implement
cross-process advisory locks. No foreign-key constraints or async runner,
or production-safe concurrent migrations yet.
Migration filenames must be trusted Python code. Do not run untrusted migration files.

### Runner behavior

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
runner milestone. `status()` currently creates the
history table if needed and lists only files present in the migration directory.

See [Stage 1 verification notes](docs/stage1.md) for the local verification status.
See [Schema Builder milestone notes](docs/stage3.md) for the current builder
verification status and changes in column defaults.
