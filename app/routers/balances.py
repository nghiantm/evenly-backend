from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.balance import GroupBalanceResponse, MyBalancesResponse
from app.services import balances as balance_service
from app.services import groups as group_service

router = APIRouter(tags=["balances"])


@router.get("/groups/{group_id}/balances", response_model=GroupBalanceResponse)
async def get_group_balances(
    group_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get balance summary for all members in a group."""
    await group_service.assert_active_member(db, group_id, current_user.id)
    return await balance_service.get_group_balances(db, group_id)


@router.get("/groups/{group_id}/balances/recalculate", status_code=204)
async def recalculate_group_balances(
    group_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recalculate all GroupTransfer records from scratch for a group."""
    membership = await group_service.assert_active_member(db, group_id, current_user.id)
    if membership.role not in ("OWNER", "ADMIN"):
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403, detail="Only OWNER or ADMIN can trigger recalculation"
        )
    await balance_service.recalculate_group_balances(db, group_id)


@router.get("/users/me/balances", response_model=MyBalancesResponse)
async def get_my_balances(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's aggregate balance across all groups."""
    return await balance_service.get_my_balances(db, current_user.id)
