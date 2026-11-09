import app.models  # Register all application models.

from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable

from app.db.base import Base


def main() -> None:
    configure_mappers()

    for table in Base.metadata.sorted_tables:
        if table.schema != "proofvault":
            continue

        # Verify PostgreSQL table SQL can be generated.
        str(CreateTable(table).compile(dialect=postgresql.dialect()))

        print(f"{table.fullname}: {', '.join(table.columns.keys())}")

    print("Model mappings and PostgreSQL table compilation passed.")


if __name__ == "__main__":
    main()