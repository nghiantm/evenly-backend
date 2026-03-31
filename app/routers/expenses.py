import math
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.expense import (
    CreateExpenseRequest,
    ExpenseListResponse,
    ExpenseResponse,
    UpdateExpenseRequest,
)
from app.services import expenses as expense_service
from app.services import groups as group_service

router = APIRouter(prefix="/groups/{group_id}/expenses", tags=["expenses"])


@router.post("", response_model=ExpenseResponse, status_code=201)
async def create_expense(
    group_id: UUID,
    data: CreateExpenseRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new expense in a group."""
    if data.groupId != group_id:
        raise HTTPException(status_code=422, detail="groupId in body must match group_id in URL")
    await group_service.assert_active_member(db, group_id, current_user.id)
    group = await group_service.get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    expense = await expense_service.create_expense(
        db, group_id, current_user, data,
        group_default_currency=group.default_currency,
    )
    return ExpenseResponse.from_orm_model(expense)


@router.get("", response_model=ExpenseListResponse)
async def list_expenses(
    group_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    created_by: UUID = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List expenses in a group with pagination."""
    await group_service.assert_active_member(db, group_id, current_user.id)
    expenses, total = await expense_service.list_expenses(
        db, group_id, page=page, page_size=page_size, created_by=created_by
    )
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    return ExpenseListResponse(
        expenses=[ExpenseResponse.from_orm_model(e) for e in expenses],
        total=total,
        page=page,
        pageSize=page_size,
        totalPages=total_pages,
    )


@router.get("/{expense_id}", response_model=ExpenseResponse)
async def get_expense(
    group_id: UUID,
    expense_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single expense by ID."""
    await group_service.assert_active_member(db, group_id, current_user.id)
    expense = await expense_service.get_expense(db, expense_id)
    if expense is None or expense.group_id != group_id:
        raise HTTPException(status_code=404, detail="Expense not found")
    return ExpenseResponse.from_orm_model(expense)


@router.patch("/{expense_id}", response_model=ExpenseResponse)
async def update_expense(
    group_id: UUID,
    expense_id: UUID,
    data: UpdateExpenseRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an expense. Only the creator can update it."""
    membership = await group_service.assert_active_member(db, group_id, current_user.id)
    expense = await expense_service.get_expense(db, expense_id)
    if expense is None or expense.group_id != group_id:
        raise HTTPException(status_code=404, detail="Expense not found")

    if expense.created_by != current_user.id and membership.role not in ("OWNER", "ADMIN"):
        raise HTTPException(
            status_code=403,
            detail="Only the expense creator or group admin can update this expense",
        )

    group = await group_service.get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    updated = await expense_service.update_expense(
        db, expense, data,
        group_default_currency=group.default_currency,
    )
    return ExpenseResponse.from_orm_model(updated)


@router.delete("/{expense_id}", status_code=204)
async def delete_expense(
    group_id: UUID,
    expense_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete an expense."""
    membership = await group_service.assert_active_member(db, group_id, current_user.id)
    expense = await expense_service.get_expense(db, expense_id)
    if expense is None or expense.group_id != group_id:
        raise HTTPException(status_code=404, detail="Expense not found")

    if expense.created_by != current_user.id and membership.role not in ("OWNER", "ADMIN"):
        raise HTTPException(
            status_code=403,
            detail="Only the expense creator or group admin can delete this expense",
        )

    await expense_service.delete_expense(db, expense)
