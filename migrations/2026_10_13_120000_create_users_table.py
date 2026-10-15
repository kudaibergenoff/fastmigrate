from fastmigrate import Migration, Schema

class CreateUsersTable(Migration):
    def up(self):
        def build(table):
            table.id()
            table.string("name")
            table.string("email").unique()
            table.boolean("active").default(True)
            table.timestamps()
        Schema.create("users", build)

    def down(self):
        Schema.drop_if_exists("users")
