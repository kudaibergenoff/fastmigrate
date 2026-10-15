import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema


@pytest.fixture
def postgres_engine():
    """Use only an explicitly configured test DB and a new schema per test."""
    database_url = os.getenv("FASTMIGRATE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set FASTMIGRATE_TEST_DATABASE_URL to run PostgreSQL integration tests")
    url = make_url(database_url)
    if url.drivername != "postgresql+psycopg":
        pytest.fail("FASTMIGRATE_TEST_DATABASE_URL must use postgresql+psycopg")

    # Never use DATABASE_URL implicitly, or drop existing schemas/tables.
    schema = "fastmigrate_test_" + uuid4().hex
    admin = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 10})
    engine = None
    created = False
    try:
        with admin.begin() as conn:
            conn.execute(CreateSchema(schema))
        created = True
        engine = create_engine(
            url,
            poolclass=NullPool,
            connect_args={
                "connect_timeout": 10,
                "options": f"-csearch_path={schema} -clock_timeout=5000 -cstatement_timeout=15000",
            },
        )
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        try:
            if created:
                with admin.begin() as conn:
                    conn.execute(DropSchema(schema, cascade=True))
        finally:
            admin.dispose()
