"""Foreign-key declarations with explicit targets and validated referential actions."""

from sqlalchemy import Column, ForeignKeyConstraint, MetaData, Table

from .blueprint import object_name


def _names(value):
    names = [value] if isinstance(value, str) else list(value)
    if not names or any(not isinstance(n, str) or not n or "\x00" in n for n in names):
        raise ValueError("Foreign-key columns must be non-empty identifiers")
    if len(set(names)) != len(names):
        raise ValueError("Foreign-key columns must be distinct")
    return names


class ForeignKeyDefinition:
    ACTIONS = {"CASCADE", "SET NULL", "RESTRICT", "NO ACTION", "SET DEFAULT"}

    def __init__(self, blueprint, columns, name=None):
        self.blueprint = blueprint
        self.columns = _names(columns)
        blueprint._columns(self.columns)
        self.name = name or object_name(blueprint.table.name, self.columns, "foreign")
        self.target_columns = None
        self.constraint = None
        self.target = None
        self.delete_action = None
        self.update_action = None

    def references(self, columns):
        if self.constraint is not None:
            raise ValueError("Foreign-key target is already bound")
        columns = _names(columns)
        if len(columns) != len(self.columns):
            raise ValueError("Foreign keys must reference the same number of columns")
        self.target_columns = columns
        return self

    def on(self, table, *, schema=None):
        if self.constraint is not None:
            raise ValueError("Foreign-key target is already bound")
        if self.target_columns is None:
            raise ValueError("Call references() before on()")
        if not isinstance(table, str) or not table or "\x00" in table:
            raise ValueError("Target table must be a non-empty identifier")
        if schema is not None and (not isinstance(schema, str) or not schema or "\x00" in schema):
            raise ValueError("Target schema must be a non-empty identifier")
        # Column objects preserve identifier boundaries, including literal dots.
        # This metadata is only a target descriptor; its table is never created.
        self.target = Table(table, MetaData(), *(Column(n) for n in self.target_columns), schema=schema)
        self._bind()
        return self

    def _bind(self):
        self.constraint = ForeignKeyConstraint(
            self.columns, [self.target.c[n] for n in self.target_columns],
            name=self.name, ondelete=self.delete_action, onupdate=self.update_action,
        )
        self.blueprint.table.append_constraint(self.constraint)

    def rebind_if_needed(self):
        # SQLAlchemy removes a ForeignKeyConstraint when a placeholder column is
        # replaced. Reconstruct it against the current column collection.
        if self.constraint is not None and self.constraint not in self.blueprint.table.constraints:
            self._bind()

    def _action(self, value):
        if not isinstance(value, str):
            raise ValueError("Foreign-key action must be a string")
        value = " ".join(value.upper().split())
        if value not in self.ACTIONS:
            raise ValueError(f"Unsupported foreign-key action: {value!r}")
        return value

    def on_delete(self, action):
        self.delete_action = self._action(action)
        if self.constraint is not None:
            self.constraint.ondelete = self.delete_action
        return self

    def on_update(self, action):
        self.update_action = self._action(action)
        if self.constraint is not None:
            self.constraint.onupdate = self.update_action
        return self

    def validate(self, nullable):
        if self.constraint is None:
            raise ValueError("Foreign key requires references() and on()")
        self.rebind_if_needed()
        if "SET NULL" in (self.delete_action, self.update_action):
            if any(not nullable.get(name, False) for name in self.columns):
                raise ValueError("SET NULL requires every foreign-key column to be nullable")
