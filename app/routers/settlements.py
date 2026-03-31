from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.settlement import (
    CreateSettlementRequest,
    SettlementListResponse,
    SettlementResponse,
)
from app.services import groups as group_service
from app.services import settlements as settlement_service

router = APIRouter(prefix="/groups/{group_id}/settlements", tags=["settlements"])


@router.post("", response_model=SettlementResponse, status_code=201)
async def create_settlement(
    group_id: UUID,
    data: CreateSettlementRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a debt settlement between two members."""
    await group_service.assert_active_member(db, group_id, current_user.id)
    settlement = await settlement_service.create_settlement(
        db, group_id, current_user, data
    )
    return SettlementResponse.from_orm_model(settlement)


@router.get("", response_model=SettlementListResponse)
async def list_settlements(
    group_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all settlements in a group."""
    await group_service.assert_active_member(db, group_id, current_user.id)
    settlements = await settlement_service.list_settlements(db, group_id)
    return SettlementListResponse(
        settlements=[SettlementResponse.from_orm_model(s) for s in settlements],
        total=len(settlements),
    )


@router.get("/{settlement_id}", response_model=SettlementResponse)
async def get_settlement(
    group_id: UUID,
    settlement_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single settlement by ID."""
    await group_service.assert_active_member(db, group_id, current_user.id)
    settlement = await settlement_service.get_settlement(db, settlement_id)
    if settlement is None or settlement.group_id != group_id:
        raise HTTPException(status_code=404, detail="Settlement not found")
    return SettlementResponse.from_orm_model(settlement)


@router.delete("/{settlement_id}", status_code=204)
async def delete_settlement(
    group_id: UUID,
    settlement_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a settlement and reverse its transfers."""
    membership = await group_service.assert_active_member(db, group_id, current_user.id)
    settlement = await settlement_service.get_settlement(db, settlement_id)
    if settlement is None or settlement.group_id != group_id:
        raise HTTPException(status_code=404, detail="Settlement not found")

    if settlement.created_by != current_user.id and membership.role not in ("OWNER", "ADMIN"):
        raise HTTPException(
            status_code=403,
            detail="Only the settlement creator or group admin can delete this settlement",
        )

    await settlement_service.delete_settlement(db, settlement)
