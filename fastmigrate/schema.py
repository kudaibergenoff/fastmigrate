from contextvars import ContextVar
from sqlalchemy import MetaData, Table
from .blueprint import Blueprint

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
        metadata = MetaData()
        blueprint = Blueprint(name, metadata)
        callback(blueprint)
        blueprint.table.create(cls._connection(), checkfirst=False)

    @classmethod
    def drop_if_exists(cls, name):
        Table(name, MetaData()).drop(cls._connection(), checkfirst=True)
