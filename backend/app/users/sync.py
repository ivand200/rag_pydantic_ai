from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.clerk import CurrentUser
from app.models.app_user import AppUser


def get_or_sync_app_user(db: Session, current_user: CurrentUser) -> AppUser:
    now = datetime.now(UTC)
    statement = (
        insert(AppUser)
        .values(
            id=uuid4(),
            clerk_user_id=current_user.user_id,
            email=current_user.email,
            first_name=current_user.first_name,
            last_name=current_user.last_name,
            created_at=now,
            updated_at=now,
            last_seen_at=now,
        )
        .on_conflict_do_update(
            index_elements=[AppUser.clerk_user_id],
            set_={
                "email": current_user.email,
                "first_name": current_user.first_name,
                "last_name": current_user.last_name,
                "updated_at": now,
                "last_seen_at": now,
            },
        )
        .returning(AppUser)
    )

    return db.execute(statement).scalar_one()
