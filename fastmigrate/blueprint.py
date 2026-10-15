"""Laravel-style table definitions, independent of database execution."""

import hashlib

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, DefaultClause,
    Float, Index, Integer, JSON, LargeBinary, Numeric, SmallInteger, String,
    Table, Text, UniqueConstraint, Uuid, false, func, true,
)
from sqlalchemy.dialects.postgresql import JSONB


def object_name(table, columns, suffix):
    name = "_".join([table, *columns, suffix])
    if len(name.encode("utf-8")) <= 63:
        return name
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    prefix = name.encode("utf-8")[:50].decode("utf-8", errors="ignore")
    return prefix + "_" + digest

class ColumnDefinition:
    def __init__(self, column, blueprint=None):
        self.column = column
        self.blueprint = blueprint
        self._unique_constraint = None
        self._unsigned_constraint = None
        self._index = None
        self.is_change = False
        self.nullable_changed = False
        self.default_changed = False
        self.comment_changed = False

    def nullable(self, value=True):
        if not isinstance(value, bool):
            raise TypeError("nullable expects a boolean")
        self.column.nullable = value
        self.nullable_changed = True
        return self

    def default(self, value):
        if isinstance(value, bool):
            self.column.server_default = DefaultClause(true() if value else false())
        elif isinstance(value, (str, int, float)):
            self.column.server_default = DefaultClause(str(value))
        else:
            raise TypeError("Unsupported server default")
        self.default_changed = True
        return self

    def drop_default(self):
        self.column.server_default = None
        self.default_changed = True
        return self

    def unique(self):
        self.column.unique = True
        if self._index is not None:
            self._index.unique = True
        elif self._unique_constraint is None:
            name = object_name(self.column.table.name, [self.column.name], "unique")
            self._unique_constraint = UniqueConstraint(self.column, name=name)
        return self

    def index(self):
        self.column.index = True
        if self._index is None:
            if self._unique_constraint is not None:
                self.column.table.constraints.remove(self._unique_constraint)
                self._unique_constraint = None
            name = object_name(self.column.table.name, [self.column.name], "index")
            self._index = Index(name, self.column, unique=bool(self.column.unique))
        return self

    def unsigned(self):
        if not isinstance(self.column.type, (Integer, Numeric, Float)):
            raise TypeError("unsigned is supported for numeric columns only")
        if self._unsigned_constraint is None:
            name = object_name(self.column.table.name, [self.column.name], "unsigned")
            self._unsigned_constraint = CheckConstraint(self.column >= 0, name=name)
            self.column.table.append_constraint(self._unsigned_constraint)
        return self

    def comment(self, value):
        if not isinstance(value, str) or "\x00" in value:
            raise TypeError("comment expects a string without null characters")
        self.column.comment = value
        self.comment_changed = True
        return self

    def change(self):
        if self.blueprint is None or not self.blueprint.alter:
            raise ValueError("change() requires Schema.table")
        self.is_change = True
        return self

class Blueprint:
    def __init__(self, name, metadata, *, alter=False):
        self.table = Table(name, metadata)
        self.alter = alter
        self.operations = []
        self._references = set()

    def _add(self, name, type_, **kwargs):
        kwargs.setdefault("nullable", False)
        col = Column(name, type_, **kwargs)
        self.table.append_column(col, replace_existing=name in self._references)
        self._references.discard(name)
        definition = ColumnDefinition(col, self)
        if self.alter:
            self.operations.append(("column", definition))
        return definition

    def id(self, name="id"):
        return self._add(name, BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)

    def uuid(self, name):
        return self._add(name, Uuid())

    def string(self, name, length=255):
        if type(length) is not int or length <= 0:
            raise ValueError("string length must be a positive integer")
        return self._add(name, String(length))

    def integer(self, name):
        return self._add(name, Integer)

    def big_integer(self, name):
        return self._add(name, BigInteger)

    def small_integer(self, name):
        return self._add(name, SmallInteger)

    def text(self, name):
        return self._add(name, Text)

    def boolean(self, name):
        return self._add(name, Boolean)

    def decimal(self, name, precision=8, scale=2):
        if type(precision) is not int or type(scale) is not int or precision <= 0 or not 0 <= scale <= precision:
            raise ValueError("decimal requires positive precision and 0 <= scale <= precision")
        return self._add(name, Numeric(precision, scale))

    def float(self, name, precision=None):
        return self._add(name, Float(precision))

    def date(self, name):
        return self._add(name, Date)

    def date_time(self, name, *, timezone=False):
        return self._add(name, DateTime(timezone=timezone))

    def timestamp(self, name, *, timezone=True):
        return self._add(name, DateTime(timezone=timezone))

    def json(self, name):
        return self._add(name, JSON)

    def jsonb(self, name):
        return self._add(name, JSONB().with_variant(JSON, "sqlite"))

    def binary(self, name):
        return self._add(name, LargeBinary)

    def foreign_id(self, name):
        return self._add(name, BigInteger)

    def timestamps(self):
        self._add("created_at", DateTime(timezone=True), server_default=func.now())
        self._add("updated_at", DateTime(timezone=True), server_default=func.now())

    def soft_deletes(self, name="deleted_at"):
        return self.timestamp(name).nullable()

    def _columns(self, names):
        names = [names] if isinstance(names, str) else list(names)
        if not names:
            raise ValueError("At least one column is required")
        for name in names:
            if name not in self.table.c:
                if not self.alter:
                    raise ValueError(f"Declare column {name!r} before creating its index or constraint")
                self.table.append_column(Column(name))
                self._references.add(name)
        return [self.table.c[name] for name in names]

    def index(self, columns, name=None):
        cols = self._columns(columns)
        name = name or object_name(self.table.name, [col.name for col in cols], "index")
        return Index(name, *cols)

    def unique(self, columns, name=None):
        cols = self._columns(columns)
        name = name or object_name(self.table.name, [col.name for col in cols], "unique")
        return UniqueConstraint(*cols, name=name)

    def _operation(self, kind, *args):
        if not self.alter:
            raise ValueError(f"{kind} requires Schema.table")
        self.operations.append((kind, args))

    def drop_column(self, name):
        self._operation("drop_column", name)

    def rename_column(self, old_name, new_name):
        self._operation("rename_column", old_name, new_name)

    def drop_index(self, name):
        self._operation("drop_index", name)

    def drop_constraint(self, name):
        self._operation("drop_constraint", name)

    def drop_unique(self, name):
        self.drop_constraint(name)
