"""DDL constructs whose identifiers are quoted by the SQLAlchemy dialect."""

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.schema import (
    AddConstraint, CreateColumn, CreateIndex, DDLElement, PrimaryKeyConstraint,
    SetColumnComment,
)


class DropTables(DDLElement):
    """Drop a set of PostgreSQL tables together, without CASCADE."""

    inherit_cache = False

    def __init__(self, tables):
        self.tables = tuple(tables)
        if not self.tables:
            raise ValueError("At least one table is required")


@compiles(DropTables, "postgresql")
def compile_drop_tables(element, compiler, **kwargs):
    names = ", ".join(compiler.preparer.format_table(table) for table in element.tables)
    return "DROP TABLE " + names


class AddColumn(DDLElement):
    inherit_cache = False

    def __init__(self, table, column):
        self.table, self.column = table, column


class TableOperation(DDLElement):
    inherit_cache = False

    def __init__(self, table, operation, *names):
        self.table, self.operation, self.names = table, operation, names


class AlterColumn(DDLElement):
    inherit_cache = False

    def __init__(self, table, definition):
        self.table, self.definition = table, definition


@compiles(AddColumn)
def compile_add_column(element, compiler, **kwargs):
    table = compiler.preparer.format_table(element.table)
    column = compiler.process(CreateColumn(element.column))
    return f"ALTER TABLE {table} ADD COLUMN {column}"


@compiles(TableOperation)
def compile_table_operation(element, compiler, **kwargs):
    table = compiler.preparer.format_table(element.table)
    names = [compiler.preparer.quote(name) for name in element.names]
    if element.operation == "rename_table":
        return f"ALTER TABLE {table} RENAME TO {names[0]}"
    if element.operation == "rename_column":
        return f"ALTER TABLE {table} RENAME COLUMN {names[0]} TO {names[1]}"
    if element.operation == "drop_column":
        return f"ALTER TABLE {table} DROP COLUMN {names[0]}"
    if element.operation == "drop_index":
        schema = compiler.preparer.quote_schema(element.table.schema) + "." if element.table.schema else ""
        return f"DROP INDEX {schema}{names[0]}"
    if element.operation == "drop_constraint":
        if compiler.dialect.name != "postgresql":
            raise NotImplementedError("Dropping constraints requires PostgreSQL")
        return f"ALTER TABLE {table} DROP CONSTRAINT {names[0]}"
    raise ValueError(f"Unknown table operation: {element.operation}")


@compiles(AlterColumn, "postgresql")
def compile_alter_column(element, compiler, **kwargs):
    definition = element.definition
    column = definition.column
    table = compiler.preparer.format_table(element.table)
    name = compiler.preparer.quote(column.name)
    type_sql = compiler.dialect.type_compiler.process(column.type)
    # The USING expression consists only of a quoted column and compiled type.
    actions = [f"ALTER COLUMN {name} TYPE {type_sql} USING CAST({name} AS {type_sql})"]
    if definition.nullable_changed:
        action = "DROP NOT NULL" if column.nullable else "SET NOT NULL"
        actions.append(f"ALTER COLUMN {name} {action}")
    if definition.default_changed:
        default = compiler.get_column_default_string(column)
        action = "DROP DEFAULT" if default is None else "SET DEFAULT " + default
        actions.append(f"ALTER COLUMN {name} {action}")
    return f"ALTER TABLE {table} " + ", ".join(actions)


def alter_statements(blueprint, dialect):
    """Plan and compile every statement before executing any table change."""
    table = blueprint.table
    statements = []
    constraints = [
        constraint for constraint in table.constraints
        if not isinstance(constraint, PrimaryKeyConstraint) or len(constraint.columns)
    ]
    if constraints and dialect.name != "postgresql":
        raise NotImplementedError("Adding constraints to an existing table requires PostgreSQL")
    for kind, value in blueprint.operations:
        if kind == "column":
            if value.is_change:
                if dialect.name != "postgresql":
                    raise NotImplementedError("Changing column definitions requires PostgreSQL")
                statements.append(AlterColumn(table, value))
            else:
                statements.append(AddColumn(table, value.column))
            if value.comment_changed:
                if dialect.name != "postgresql":
                    raise NotImplementedError("Column comments require PostgreSQL")
                statements.append(SetColumnComment(value.column))
        else:
            statements.append(TableOperation(table, kind, *value))
    statements.extend(AddConstraint(c) for c in sorted(constraints, key=lambda c: c.name or ""))
    statements.extend(CreateIndex(i) for i in sorted(table.indexes, key=lambda i: i.name))
    for statement in statements:
        statement.compile(dialect=dialect)
    return statements
