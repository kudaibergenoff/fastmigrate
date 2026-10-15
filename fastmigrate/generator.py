"""Generate editable Python migrations without connecting to a database."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re


NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


def make_migration(name, directory="migrations", *, create=None, table=None, now=None):
    if not NAME_PATTERN.fullmatch(name) or len(name) > 234:
        raise ValueError("Migration name must be snake_case, start with a letter and be at most 234 characters")
    if create is not None and table is not None:
        raise ValueError("--create and --table are mutually exclusive")
    for target in (create, table):
        if target is not None and (not target or "\x00" in target):
            raise ValueError("Table name must not be empty or contain a null character")

    class_name = "".join(part.capitalize() for part in name.split("_"))
    prefix = f"from fastmigrate import Migration, Schema\n\n\nclass {class_name}(Migration):\n"
    if create is not None:
        body = (
            "    def up(self):\n"
            "        def build(table):\n"
            "            table.id()\n"
            f"        Schema.create({create!r}, build)\n\n"
            "    def down(self):\n"
            f"        Schema.drop_if_exists({create!r})\n"
        )
    elif table is not None:
        body = (
            f"    table_name = {table!r}\n\n"
            "    def up(self):\n"
            "        def change(table):\n"
            "            # Define column/index changes here.\n"
            "            pass\n"
            "        Schema.table(self.table_name, change)\n\n"
            "    def down(self):\n"
            "        def change(table):\n"
            "            # Reverse the changes from up().\n"
            "            pass\n"
            "        Schema.table(self.table_name, change)\n"
        )
    else:
        body = (
            "    def up(self):\n"
            "        # Define the forward change here.\n"
            "        pass\n\n"
            "    def down(self):\n"
            "        # Define the reverse change here.\n"
            "        pass\n"
        )

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = now or datetime.now(timezone.utc)
    # Exclusive creation prevents overwrites even between simultaneous generators.
    # Advance the timestamp on collisions to retain the filename format and order.
    for offset in range(86400):
        stamp = (timestamp + timedelta(seconds=offset)).strftime("%Y_%m_%d_%H%M%S")
        path = directory / f"{stamp}_{name}.py"
        try:
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(prefix + body)
            return path
        except FileExistsError:
            continue
    raise FileExistsError("Could not allocate a unique migration filename")
