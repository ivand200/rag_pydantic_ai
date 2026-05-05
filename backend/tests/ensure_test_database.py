from __future__ import annotations

from psycopg import connect, sql
from sqlalchemy.engine import URL, make_url

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    if not settings.test_database_url:
        raise SystemExit("TEST_DATABASE_URL is required to create the test database.")

    app_url = make_url(settings.database_url)
    test_url = make_url(settings.test_database_url)
    if _same_database(app_url, test_url):
        raise SystemExit("TEST_DATABASE_URL must point at a database separate from DATABASE_URL.")

    test_database = test_url.database
    if not test_database:
        raise SystemExit("TEST_DATABASE_URL must include a database name.")

    maintenance_url = test_url.set(drivername="postgresql", database="postgres")
    with connect(
        maintenance_url.render_as_string(hide_password=False),
        autocommit=True,
    ) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (test_database,),
        ).fetchone()
        if exists:
            print(f"Test database already exists: {test_database}")
            return

        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_database)))
        print(f"Created test database: {test_database}")


def _same_database(first: URL, second: URL) -> bool:
    return (
        first.drivername == second.drivername
        and first.host == second.host
        and first.port == second.port
        and first.username == second.username
        and first.database == second.database
    )


if __name__ == "__main__":
    main()
