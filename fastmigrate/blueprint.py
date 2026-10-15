from sqlalchemy import Column, Integer, BigInteger, String, Text, Boolean, DateTime, JSON, func, DefaultClause, Index, UniqueConstraint

class ColumnDefinition:
    def __init__(self, column):
        self.column = column
        self._unique_constraint = None
        self._index = None

    def nullable(self):
        self.column.nullable = True
        return self

    def default(self, value):
        # Database-side default; accepts basic literals, not arbitrary SQL.
        from sqlalchemy import false, true
        if isinstance(value, bool):
            self.column.server_default = DefaultClause(true() if value else false())
        elif isinstance(value, (str, int, float)):
            self.column.server_default = DefaultClause(str(value))
        else:
            raise TypeError("Unsupported server default")
        return self

    def unique(self):
        # Column flags are consumed when the column is attached to a Table.
        # Blueprint has already attached it, so create the schema object here.
        self.column.unique = True
        if self._index is not None:
            self._index.unique = True
        elif self._unique_constraint is None:
            self._unique_constraint = UniqueConstraint(self.column)
        return self

    def index(self):
        self.column.index = True
        if self._index is None:
            if self._unique_constraint is not None:
                self.column.table.constraints.remove(self._unique_constraint)
                self._unique_constraint = None
            self._index = Index(None, self.column, unique=bool(self.column.unique))
        return self

class Blueprint:
    def __init__(self, name, metadata):
        from sqlalchemy import Table
        self.table = Table(name, metadata)

    def _add(self, name, type_, **kwargs):
        col = Column(name, type_, **kwargs)
        self.table.append_column(col)
        return ColumnDefinition(col)

    def id(self, name="id"):
        return self._add(name, BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)

    def string(self, name, length=255):
        return self._add(name, String(length))

    def integer(self, name):
        return self._add(name, Integer)

    def big_integer(self, name):
        return self._add(name, BigInteger)

    def text(self, name):
        return self._add(name, Text)

    def boolean(self, name):
        return self._add(name, Boolean)

    def json(self, name):
        return self._add(name, JSON)

    def timestamps(self):
        self._add("created_at", DateTime(timezone=True), server_default=func.now())
        self._add("updated_at", DateTime(timezone=True), server_default=func.now())
