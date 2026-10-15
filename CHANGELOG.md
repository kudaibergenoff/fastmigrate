# Changelog

## 0.2.0 — Unreleased

### Added

- Click CLI and console entry point; module/manage.py invocation.
- Migration generation, last-N rollback, reset, refresh and fresh commands.
- PostgreSQL column types, schema inspection/rename/drop and ALTER TABLE builder.
- Named indexes and unique/CHECK constraints; numeric unsigned checks.
- PostgreSQL integration tests and CI service configuration.

### Changed

- New column definitions default to NOT NULL; use `.nullable()` for optional
  values. `.change()` preserves nullable/default/comment unless explicitly set.
- Generated index and constraint names are deterministic and fit PostgreSQL's
  identifier byte limit.

### Fixed

- Unique/index modifiers now create actual SQLAlchemy schema objects.
- A class alias no longer counts as a second migration class.
- Missing migration directories are rejected before migrate/status transactions.

### Pending

- CLI and PostgreSQL runtime verification in the current environment.
- Foreign keys, migration repository/history upgrade, advisory locking and
  transaction-per-migration semantics before v0.2.0 release acceptance.
