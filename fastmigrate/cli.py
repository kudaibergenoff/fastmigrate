"""Command-line interface. Database connections are opened only by DB commands."""

from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version

import click
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from .generator import make_migration
from .runner import MigrationRunner


def _version():
    try:
        return version("fastmigrate")
    except PackageNotFoundError:
        return "development"


def _error_message(exc, database_url):
    # SQLAlchemy's full error string may include SQL parameters; prefer the
    # driver's first diagnostic line, then redact connection credentials.
    cause = getattr(exc, "orig", None) or exc
    lines = str(cause).splitlines()
    detail = lines[0] if lines else type(exc).__name__
    if database_url:
        detail = detail.replace(database_url, "<database URL>")
        try:
            password = make_url(database_url).password
            if password:
                detail = detail.replace(password, "***")
        except Exception:
            pass
    prefix = "Database error" if isinstance(exc, SQLAlchemyError) else type(exc).__name__
    return f"{prefix}: {detail}"


@contextmanager
def _runner(options):
    url = options["database_url"]
    if not url:
        raise click.ClickException("Set DATABASE_URL or pass --database-url before the command")
    engine = None
    try:
        engine = create_engine(url, hide_parameters=True)
        yield MigrationRunner(engine, options["migrations_path"])
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(_error_message(exc, url)) from exc
    finally:
        if engine is not None:
            engine.dispose()


def _show(names, action, empty):
    if not names:
        click.echo(empty)
    for name in names:
        click.echo(f"{action}: {name}")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--database-url", envvar="DATABASE_URL", help="SQLAlchemy URL; defaults to DATABASE_URL.")
@click.option(
    "--migrations-path", envvar="MIGRATIONS_PATH", default="migrations",
    type=click.Path(file_okay=False, path_type=str), show_default=True,
    help="Migration directory; defaults to MIGRATIONS_PATH.",
)
@click.version_option(version=_version(), prog_name="fastmigrate")
@click.pass_context
def cli(ctx, database_url, migrations_path):
    """Laravel-inspired database migrations for Python projects."""
    ctx.obj = {"database_url": database_url, "migrations_path": migrations_path}


@cli.command("make:migration")
@click.argument("name")
@click.option("--create", "create_table", help="Generate a working create/drop-table migration.")
@click.option("--table", "target_table", help="Generate an editable scaffold for an existing table.")
@click.pass_obj
def make(options, name, create_table, target_table):
    """Create a timestamped migration file without overwriting existing files."""
    try:
        path = make_migration(name, options["migrations_path"], create=create_table, table=target_table)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Created: {path}")
    if target_table is not None:
        click.echo("Created an editable table scaffold; define up() and down() before applying it.")


@cli.command("migrate")
@click.pass_obj
def migrate(options):
    """Apply pending migrations in filename order."""
    with _runner(options) as runner:
        names = runner.migrate()
    _show(names, "Applied", "Nothing to migrate.")


@cli.command("migrate:status")
@click.pass_obj
def status(options):
    """List discovered migration files and their applied status."""
    with _runner(options) as runner:
        rows = runner.status()
    if not rows:
        click.echo("No migrations found.")
    for name, applied in rows:
        click.echo(f"{'Applied' if applied else 'Pending':<9} {name}")


@cli.command("migrate:rollback")
@click.option("--step", type=click.IntRange(min=1), help="Reverse the last N migrations across batches.")
@click.pass_obj
def rollback(options, step):
    """Reverse the last batch, or the last N migrations with --step."""
    with _runner(options) as runner:
        names = runner.rollback(step=step)
    _show(names, "Rolled back", "Nothing to rollback.")


@cli.command("migrate:reset")
@click.pass_obj
def reset(options):
    """Reverse all applied migrations (this can delete data)."""
    with _runner(options) as runner:
        names = runner.reset()
    _show(names, "Rolled back", "Nothing to reset.")


@cli.command("migrate:refresh")
@click.pass_obj
def refresh(options):
    """Reverse all applied migrations and reapply (this can delete data)."""
    with _runner(options) as runner:
        names = runner.refresh()
    _show(names, "Applied", "No migrations to refresh.")


@cli.command("migrate:fresh")
@click.option("--force", is_flag=True, help="Confirm deletion without an interactive prompt.")
@click.pass_obj
def fresh(options, force):
    """Drop ALL tables in the current schema and reapply migrations."""
    if not force:
        click.confirm("Drop ALL tables and their data in the current database schema?", abort=True)
    with _runner(options) as runner:
        names = runner.fresh()
    _show(names, "Applied", "Tables dropped. No migrations to apply.")
