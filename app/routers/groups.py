from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.expense import Expense
from app.models.group import GroupMember
from app.models.settlement import Settlement
from app.models.user import User
from app.schemas.group import (
    AddMemberRequest,
    CreateGroupRequest,
    GroupDetailResponse,
    GroupMemberResponse,
    GroupResponse,
    UpdateGroupRequest,
)
from app.services import balances as balance_service
from app.services import groups as group_service
from app.services import users as user_service

router = APIRouter(prefix="/groups", tags=["groups"])


@router.post("", response_model=GroupResponse, status_code=201)
async def create_group(
    data: CreateGroupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new group. The creator becomes the OWNER."""
    group = await group_service.create_group(db, current_user, data)
    active_members = await group_service.get_active_members(db, group.id)
    return GroupResponse.from_orm_model(
        group, my_role="OWNER", member_count=len(active_members)
    )


@router.get("", response_model=List[GroupResponse])
async def list_groups(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all groups the current user is a member of."""
    groups = await group_service.list_user_groups(db, current_user)
    response = []
    for group in groups:
        membership = await group_service.get_membership(db, group.id, current_user.id)
        active_members = [m for m in group.members if m.left_at is None]
        role = membership.role if membership else "MEMBER"
        response.append(
            GroupResponse.from_orm_model(
                group, my_role=role, member_count=len(active_members)
            )
        )
    return response


@router.get("/{group_id}", response_model=GroupDetailResponse)
async def get_group(
    group_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed info about a group."""
    group = await group_service.get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    membership = await group_service.assert_active_member(db, group_id, current_user.id)

    active_members = [m for m in group.members if m.left_at is None]
    member_responses = [GroupMemberResponse.from_orm_model(m) for m in active_members]

    # Recent counts (last 30 days not enforced, just total counts for now)
    expense_count_result = await db.execute(
        select(func.count()).where(
            Expense.group_id == group_id,
            Expense.deleted_at.is_(None),
        )
    )
    recent_expense_count = expense_count_result.scalar_one()

    settlement_count_result = await db.execute(
        select(func.count()).where(Settlement.group_id == group_id)
    )
    recent_settlement_count = settlement_count_result.scalar_one()

    return GroupDetailResponse.from_orm_model_detail(
        group=group,
        my_role=membership.role,
        member_count=len(active_members),
        members=member_responses,
        recent_expense_count=recent_expense_count,
        recent_settlement_count=recent_settlement_count,
    )


@router.patch("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: UUID,
    data: UpdateGroupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update group settings. Requires OWNER or ADMIN role."""
    group = await group_service.get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    membership = await group_service.assert_active_member(db, group_id, current_user.id)
    if membership.role not in ("OWNER", "ADMIN"):
        raise HTTPException(
            status_code=403, detail="Only OWNER or ADMIN can update group settings"
        )

    group = await group_service.update_group(db, group, data)
    active_members = await group_service.get_active_members(db, group.id)
    return GroupResponse.from_orm_model(
        group, my_role=membership.role, member_count=len(active_members)
    )


@router.delete("/{group_id}", status_code=204)
async def archive_group(
    group_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Archive a group. Requires OWNER role."""
    group = await group_service.get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    membership = await group_service.assert_active_member(db, group_id, current_user.id)
    if membership.role != "OWNER":
        raise HTTPException(status_code=403, detail="Only OWNER can archive the group")

    await group_service.archive_group(db, group)


@router.post("/{group_id}/members", response_model=GroupMemberResponse, status_code=201)
async def add_member(
    group_id: UUID,
    data: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a member to the group. Requires OWNER or ADMIN role."""
    group = await group_service.get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    membership = await group_service.assert_active_member(db, group_id, current_user.id)
    if membership.role not in ("OWNER", "ADMIN"):
        raise HTTPException(
            status_code=403, detail="Only OWNER or ADMIN can add members"
        )

    user_to_add = await user_service.get_user_by_id(db, data.userId)
    if user_to_add is None:
        raise HTTPException(status_code=404, detail="User not found")

    new_membership = await group_service.add_member(db, group, user_to_add, role=data.role)

    # Load user for response
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select as sa_select
    result = await db.execute(
        sa_select(GroupMember)
        .where(GroupMember.group_id == group_id)
        .where(GroupMember.user_id == data.userId)
        .options(selectinload(GroupMember.user))
    )
    refreshed = result.scalar_one()
    return GroupMemberResponse.from_orm_model(refreshed)


@router.delete("/{group_id}/members/{user_id}", status_code=204)
async def remove_member(
    group_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member from the group."""
    group = await group_service.get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    my_membership = await group_service.assert_active_member(db, group_id, current_user.id)

    # User can remove themselves, OWNER/ADMIN can remove others
    if user_id != current_user.id and my_membership.role not in ("OWNER", "ADMIN"):
        raise HTTPException(
            status_code=403, detail="Only OWNER or ADMIN can remove other members"
        )

    # Reject removal if the member has an unsettled balance
    group_balances = await balance_service.get_group_balances(db, group_id)
    for ub in group_balances.userBalances:
        if ub.userId == user_id and abs(ub.netAmount) > 0.01:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove member with an unsettled balance. Please settle all debts first.",
            )

    await group_service.remove_member(db, group_id, user_id)
