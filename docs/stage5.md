# Stage 5: foreign keys, primary keys and composite indexes

## Implemented

- `foreign_id(...).constrained(table, column="id", name=None, schema=None)`.
- `foreign(columns, name).references(columns).on(table, schema=...)` for
  single/composite foreign keys.
- Validated ON DELETE/ON UPDATE actions, including CASCADE and SET NULL.
- Named/composite primary keys, unique indexes and deterministic generated names.
- Foreign/primary constraint removal by name, or by a generated local-column name
  for foreign keys.
- Explicit final-column/nullability validation before DDL. Renamed/dropped
  columns cannot be used accidentally by deferred constraints or indexes.
- PostgreSQL creation order: primary/unique constraints, indexes, foreign keys.
  New-table PostgreSQL FKs are installed after Table.create has emitted indexes.

## Independent review

At the user's request, a separate reviewer agent reviewed this stage read-only,
then re-reviewed fixes twice. It found two P1 issues and one P2 issue:

1. SQLAlchemy removed an FK when a referenced placeholder was replaced by a
   column `.change()` declaration. Bound FK descriptors are now reconstructed
   against the final column collection when necessary.
2. Self-FKs could be installed before the unique index/constraint they require.
   CREATE/ALTER planning now creates uniqueness before dependent FKs.
3. A pending FK could reference a column renamed later in the callback. The
   conflicting combination is rejected before DDL; declaring the FK through the
   final name is supported.

Regression tests were added for all three findings. Final reviewer result:
**no substantial new findings**, with **17 FK tests passed** independently.

## Verification and limits

- The FK suite executes with SQLite foreign-key enforcement explicitly enabled.
  PostgreSQL SQL/operation ordering is checked by dialect compilation/mock engine.
- Full accessible regression run: **93 passed, 26 PostgreSQL tests skipped**.
- Real PostgreSQL integration remains unexecuted in this session. Its test cases
  cover enforcement, cascades, SET NULL, composite keys, ALTER, placeholder
  replacement and self-FKs on newly created unique indexes.
- CLI tests remain explicitly excluded because Click is not installed in the
  agent's environment. This is not a passing CLI result.
- JUnit report: `.tmp/stage5-results.xml` (ignored by Git). Successful local pytest
  runs continue to use the invocation-local workspace tmp_path fixture described
  in stage1.md; application code and assertions are not replaced.

The next runner stage adds repository/history upgrades, advisory locking and
transaction-per-migration semantics. No release readiness is claimed before those
requirements and actual PostgreSQL integration checks are complete.
