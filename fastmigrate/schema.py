from contextvars import ContextVar
from sqlalchemy import MetaData, Table, inspect
from sqlalchemy.exc import NoSuchTableError
from .blueprint import Blueprint
from .compiler import TableOperation, alter_statements

_connection = ContextVar("fastmigrate_connection", default=None)

class Schema:
    @staticmethod
    def _connection():
        conn = _connection.get()
        if conn is None:
            raise RuntimeError("Schema operations require an active MigrationRunner")
        return conn

    @classmethod
    def create(cls, name, callback):
        conn = cls._connection()
        metadata = MetaData()
        blueprint = Blueprint(name, metadata)
        callback(blueprint)
        blueprint.table.create(conn, checkfirst=False)

    @classmethod
    def table(cls, name, callback):
        conn = cls._connection()
        if not inspect(conn).has_table(name):
            raise NoSuchTableError(name)
        blueprint = Blueprint(name, MetaData(), alter=True)
        callback(blueprint)
        for statement in alter_statements(blueprint, conn.dialect):
            conn.execute(statement)

    @classmethod
    def drop(cls, name):
        Table(name, MetaData()).drop(cls._connection(), checkfirst=False)

    @classmethod
    def drop_if_exists(cls, name):
        Table(name, MetaData()).drop(cls._connection(), checkfirst=True)

    @classmethod
    def has_table(cls, name):
        return inspect(cls._connection()).has_table(name)

    @classmethod
    def has_column(cls, table, column):
        inspector = inspect(cls._connection())
        if not inspector.has_table(table):
            return False
        return any(item["name"] == column for item in inspector.get_columns(table))

    @classmethod
    def rename(cls, old_name, new_name):
        cls._connection().execute(TableOperation(Table(old_name, MetaData()), "rename_table", new_name))
