from typing import Optional
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import UpdateUserRequest


async def get_or_create_user(
    db: AsyncSession,
    external_subject: str,
    email: str,
    display_name: str,
    email_verified: bool,
    image_url: Optional[str] = None,
) -> User:
    """Upsert a user by external_subject (Clerk sub claim)."""
    result = await db.execute(
        select(User).where(User.external_subject == external_subject)
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            external_subject=external_subject,
            email=email,
            display_name=display_name,
            email_verified=email_verified,
            avatar_url=image_url,
        )
        db.add(user)
        try:
            await db.commit()
            await db.refresh(user)
        except IntegrityError:
            # Another row already owns this email (e.g. account re-created in Clerk).
            # Roll back, fetch the existing row, and re-link it to the current subject.
            await db.rollback()
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalar_one()
            user.external_subject = external_subject
            user.email_verified = email_verified
            if display_name:
                user.display_name = display_name
            if image_url and not user.avatar_url:
                user.avatar_url = image_url
            await db.commit()
            await db.refresh(user)
        return user
    else:
        # Update mutable fields if they changed
        changed = False
        if user.email != email:
            user.email = email
            changed = True
        if user.email_verified != email_verified:
            user.email_verified = email_verified
            changed = True
        if display_name and user.display_name != display_name:
            user.display_name = display_name
            changed = True
        if image_url and user.avatar_url != image_url:
            user.avatar_url = image_url
            changed = True
        if changed:
            await db.commit()
            await db.refresh(user)

    return user


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def search_users(db: AsyncSession, q: str, limit: int = 10) -> list[User]:
    pattern = f"%{q}%"
    result = await db.execute(
        select(User)
        .where(
            or_(
                User.email.ilike(pattern),
                User.display_name.ilike(pattern),
            )
        )
        .limit(limit)
    )
    return list(result.scalars().all())


async def update_user(db: AsyncSession, user: User, data: UpdateUserRequest) -> User:
    if data.displayName is not None:
        user.display_name = data.displayName
    if data.defaultCurrency is not None:
        user.default_currency = data.defaultCurrency
    if data.avatarUrl is not None:
        user.avatar_url = data.avatarUrl
    await db.commit()
    await db.refresh(user)
    return user
