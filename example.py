import os
from sqlalchemy import create_engine
from fastmigrate import MigrationRunner

engine = create_engine(os.getenv("DATABASE_URL", "sqlite+pysqlite:///demo.db"))
runner = MigrationRunner(engine, "migrations")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["migrate", "rollback", "status"])
    args = parser.parse_args()
    print(getattr(runner, args.command)())
