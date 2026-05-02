from sqlalchemy import text
from sqlalchemy.engine import Engine


def test_app_users_migration_creates_required_identity_constraints(
    migrated_database: Engine,
) -> None:
    with migrated_database.connect() as connection:
        columns = {
            row.column_name: row
            for row in connection.execute(
                text(
                    """
                    SELECT column_name, is_nullable, data_type, udt_name
                    FROM information_schema.columns
                    WHERE table_name = 'app_users'
                    """
                )
            )
        }
        unique_constraints = {
            row.constraint_name
            for row in connection.execute(
                text(
                    """
                    SELECT tc.constraint_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.constraint_column_usage ccu
                      ON tc.constraint_name = ccu.constraint_name
                    WHERE tc.table_name = 'app_users'
                      AND tc.constraint_type = 'UNIQUE'
                      AND ccu.column_name = 'clerk_user_id'
                    """
                )
            )
        }

    assert columns["id"].udt_name == "uuid"
    assert columns["clerk_user_id"].is_nullable == "NO"
    assert "uq_app_users_clerk_user_id" in unique_constraints
