from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.group import Group, GroupMember
from app.models.user import User
from app.schemas.group import UpdateGroupRequest


async def create_group(
    db: AsyncSession,
    user: User,
    data,
) -> Group:
    group = Group(
        name=data.name,
        default_currency=data.defaultCurrency,
        created_by=user.id,
    )
    db.add(group)
    await db.flush()  # get group.id before adding member

    membership = GroupMember(
        group_id=group.id,
        user_id=user.id,
        role="OWNER",
    )
    db.add(membership)
    await db.commit()
    await db.refresh(group)
    return group


async def list_user_groups(db: AsyncSession, user: User) -> list[Group]:
    result = await db.execute(
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.user_id == user.id)
        .where(GroupMember.left_at.is_(None))
        .options(selectinload(Group.members).selectinload(GroupMember.user))
        .order_by(Group.created_at.desc())
    )
    return list(result.scalars().unique().all())


async def get_group(db: AsyncSession, group_id: UUID) -> Optional[Group]:
    result = await db.execute(
        select(Group)
        .where(Group.id == group_id)
        .options(selectinload(Group.members).selectinload(GroupMember.user))
    )
    return result.scalar_one_or_none()


async def get_membership(
    db: AsyncSession, group_id: UUID, user_id: UUID
) -> Optional[GroupMember]:
    result = await db.execute(
        select(GroupMember)
        .where(GroupMember.group_id == group_id)
        .where(GroupMember.user_id == user_id)
        .where(GroupMember.left_at.is_(None))
        .options(selectinload(GroupMember.user))
    )
    return result.scalar_one_or_none()


async def assert_active_member(
    db: AsyncSession, group_id: UUID, user_id: UUID
) -> GroupMember:
    membership = await get_membership(db, group_id, user_id)
    if membership is None:
        raise HTTPException(
            status_code=403, detail="You are not an active member of this group"
        )
    return membership


async def update_group(
    db: AsyncSession, group: Group, data: UpdateGroupRequest
) -> Group:
    if data.name is not None:
        group.name = data.name
    if data.defaultCurrency is not None:
        group.default_currency = data.defaultCurrency
    if data.simplifyDebts is not None:
        group.simplify_debts = data.simplifyDebts
    await db.commit()
    await db.refresh(group)
    return group


async def archive_group(db: AsyncSession, group: Group) -> Group:
    group.archived_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(group)
    return group


async def add_member(
    db: AsyncSession,
    group: Group,
    user: User,
    role: str = "MEMBER",
) -> GroupMember:
    # Check if already a member (possibly re-joining)
    result = await db.execute(
        select(GroupMember)
        .where(GroupMember.group_id == group.id)
        .where(GroupMember.user_id == user.id)
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        if existing.left_at is None:
            raise HTTPException(
                status_code=409, detail="User is already a member of this group"
            )
        # Re-activate
        existing.left_at = None
        existing.role = role
        await db.commit()
        await db.refresh(existing)
        return existing

    membership = GroupMember(
        group_id=group.id,
        user_id=user.id,
        role=role,
    )
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return membership


async def remove_member(
    db: AsyncSession, group_id: UUID, user_id: UUID
) -> None:
    membership = await get_membership(db, group_id, user_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Member not found in group")

    # Check for unresolved balances
    from app.services.balances import get_member_balance

    net_balance = await get_member_balance(db, group_id, user_id)
    if net_balance != 0:
        raise HTTPException(
            status_code=409,
            detail=f"User has unresolved balance of {net_balance}. Settle debts before removing.",
        )

    membership.left_at = datetime.now(timezone.utc)
    await db.commit()


async def get_active_members(db: AsyncSession, group_id: UUID) -> list[GroupMember]:
    result = await db.execute(
        select(GroupMember)
        .where(GroupMember.group_id == group_id)
        .where(GroupMember.left_at.is_(None))
        .options(selectinload(GroupMember.user))
    )
    return list(result.scalars().all())
