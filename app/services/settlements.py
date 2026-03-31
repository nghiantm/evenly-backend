from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.expense import GroupTransfer
from app.models.group import GroupMember
from app.models.settlement import Settlement
from app.models.user import User
from app.schemas.settlement import CreateSettlementRequest


async def create_settlement(
    db: AsyncSession,
    group_id: UUID,
    current_user: User,
    data: CreateSettlementRequest,
) -> Settlement:
    # Validate both users are active members
    for uid in (data.fromUserId, data.toUserId):
        result = await db.execute(
            select(GroupMember)
            .where(GroupMember.group_id == group_id)
            .where(GroupMember.user_id == uid)
            .where(GroupMember.left_at.is_(None))
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=422,
                detail=f"User {uid} is not an active member of the group",
            )

    if data.fromUserId == data.toUserId:
        raise HTTPException(
            status_code=422, detail="fromUserId and toUserId must be different"
        )

    if data.amount <= 0:
        raise HTTPException(status_code=422, detail="Amount must be positive")

    settlement = Settlement(
        group_id=group_id,
        created_by=current_user.id,
        from_user_id=data.fromUserId,
        to_user_id=data.toUserId,
        currency=data.currency,
        amount=data.amount,
        settlement_date=data.settlementDate,
        note=data.note,
    )
    db.add(settlement)
    await db.flush()  # get settlement.id

    # Settlement reduces debt: from_user paid to_user.
    # This means to_user's credit from_user is reduced.
    # We create a transfer in the opposite direction of the original debt:
    # from_user (payer) -> to_user (receiver), representing the payoff.
    # In balance calculation: to_user gains credit back.
    transfer = GroupTransfer(
        group_id=group_id,
        settlement_id=settlement.id,
        from_user_id=data.toUserId,   # creditor gives back credit
        to_user_id=data.fromUserId,   # debtor's debt is reduced
        currency=data.currency,
        amount=data.amount,
    )
    db.add(transfer)

    await db.commit()
    await db.refresh(settlement)
    return settlement


async def list_settlements(
    db: AsyncSession,
    group_id: UUID,
) -> list[Settlement]:
    result = await db.execute(
        select(Settlement)
        .where(Settlement.group_id == group_id)
        .order_by(Settlement.settlement_date.desc(), Settlement.created_at.desc())
    )
    return list(result.scalars().all())


async def get_settlement(
    db: AsyncSession, settlement_id: UUID
) -> Optional[Settlement]:
    result = await db.execute(
        select(Settlement).where(Settlement.id == settlement_id)
    )
    return result.scalar_one_or_none()


async def delete_settlement(
    db: AsyncSession, settlement: Settlement
) -> None:
    # Delete associated transfers
    await db.execute(
        delete(GroupTransfer).where(GroupTransfer.settlement_id == settlement.id)
    )
    await db.delete(settlement)
    await db.commit()
