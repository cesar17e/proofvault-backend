from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import engine


def main() -> None:
    try:
        with engine.connect() as connection:
            result = connection.execute(
                text("SELECT 1")
            ).scalar_one()

            schema_exists = connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.schemata
                        WHERE schema_name = :schema_name
                    )
                    """
                ),
                {"schema_name": "proofvault"},
            ).scalar_one()

        print(f"Database connection successful: SELECT 1 returned {result}")
        print(f"proofvault schema exists: {schema_exists}")

    except SQLAlchemyError as exc:
        print(f"Database check failed: {type(exc).__name__}")
        print("Check the connection details, password, SSL, and network.")
        raise SystemExit(1) from None

    finally:
        engine.dispose()


if __name__ == "__main__":
    main()