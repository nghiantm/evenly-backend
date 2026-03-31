from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.expense import Expense, ExpensePayment, ExpenseSplit, GroupTransfer
from app.models.group import GroupMember
from app.models.user import User
from app.schemas.expense import CreateExpenseRequest, UpdateExpenseRequest


async def _build_transfers_for_expense(
    expense_id: UUID,
    group_id: UUID,
    currency: str,
    payments: list[ExpensePayment],
    splits: list[ExpenseSplit],
) -> list[GroupTransfer]:
    """
    For each split, determine how much the split user owes to each payer.
    Uses proportional distribution when there are multiple payers.
    """
    transfers: list[GroupTransfer] = []

    total_paid = sum(p.amount for p in payments)
    if total_paid == Decimal("0"):
        return transfers

    for split in splits:
        split_user_id = split.user_id
        amount_owed = split.amount_owed

        if amount_owed <= Decimal("0"):
            continue

        # Distribute what split_user owes proportionally across payers
        for payment in payments:
            payer_id = payment.payer_id
            if payer_id == split_user_id:
                # User owes themselves — no transfer needed
                continue

            # Proportion of this payer's contribution
            payer_share = payment.amount / total_paid
            transfer_amount = (amount_owed * payer_share).quantize(Decimal("0.01"))

            if transfer_amount > Decimal("0"):
                transfers.append(
                    GroupTransfer(
                        group_id=group_id,
                        expense_id=expense_id,
                        from_user_id=split_user_id,
                        to_user_id=payer_id,
                        currency=currency,
                        amount=transfer_amount,
                    )
                )

    return transfers


async def create_expense(
    db: AsyncSession,
    group_id: UUID,
    current_user: User,
    data: CreateExpenseRequest,
) -> Expense:
    # Validate payer amounts sum to totalAmount
    payer_total = sum(p.amount for p in data.paidBy)
    if abs(payer_total - data.totalAmount) > Decimal("0.02"):
        raise HTTPException(
            status_code=422,
            detail=f"Payer amounts ({payer_total}) must sum to totalAmount ({data.totalAmount})",
        )

    # Validate split amounts sum to totalAmount
    split_total = sum(s.amountOwed for s in data.splits)
    if abs(split_total - data.totalAmount) > Decimal("0.02"):
        raise HTTPException(
            status_code=422,
            detail=f"Split amounts ({split_total}) must sum to totalAmount ({data.totalAmount})",
        )

    # Gather all involved user IDs
    involved_user_ids = {p.userId for p in data.paidBy} | {s.userId for s in data.splits}

    # Verify all involved users are active members
    result = await db.execute(
        select(GroupMember)
        .where(GroupMember.group_id == group_id)
        .where(GroupMember.user_id.in_(involved_user_ids))
        .where(GroupMember.left_at.is_(None))
    )
    active_memberships = {m.user_id for m in result.scalars().all()}

    missing = involved_user_ids - active_memberships
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Some users are not active members of the group: {[str(uid) for uid in missing]}",
        )

    # Create expense
    expense = Expense(
        group_id=group_id,
        created_by=current_user.id,
        description=data.description,
        currency=data.currency,
        total_amount=data.totalAmount,
        expense_date=data.expenseDate,
        note=data.note,
    )
    db.add(expense)
    await db.flush()  # get expense.id

    # Create payments
    payment_objects = []
    for payer_input in data.paidBy:
        payment = ExpensePayment(
            expense_id=expense.id,
            payer_id=payer_input.userId,
            amount=payer_input.amount,
        )
        db.add(payment)
        payment_objects.append(payment)

    # Create splits
    split_objects = []
    for split_input in data.splits:
        split = ExpenseSplit(
            expense_id=expense.id,
            user_id=split_input.userId,
            amount_owed=split_input.amountOwed,
            split_type=split_input.splitType,
            shares=split_input.shares,
            percentage=split_input.percentage,
        )
        db.add(split)
        split_objects.append(split)

    await db.flush()  # ensure IDs assigned

    # Create GroupTransfer records
    transfers = await _build_transfers_for_expense(
        expense_id=expense.id,
        group_id=group_id,
        currency=data.currency,
        payments=payment_objects,
        splits=split_objects,
    )
    for t in transfers:
        db.add(t)

    await db.commit()
    await db.refresh(expense)

    # Re-load with relationships
    result = await db.execute(
        select(Expense)
        .where(Expense.id == expense.id)
        .options(
            selectinload(Expense.payments),
            selectinload(Expense.splits),
        )
    )
    return result.scalar_one()


async def get_expense(db: AsyncSession, expense_id: UUID) -> Optional[Expense]:
    result = await db.execute(
        select(Expense)
        .where(Expense.id == expense_id)
        .where(Expense.deleted_at.is_(None))
        .options(
            selectinload(Expense.payments),
            selectinload(Expense.splits),
        )
    )
    return result.scalar_one_or_none()


async def list_expenses(
    db: AsyncSession,
    group_id: UUID,
    page: int = 1,
    page_size: int = 20,
    created_by: Optional[UUID] = None,
) -> tuple[list[Expense], int]:
    base_query = (
        select(Expense)
        .where(Expense.group_id == group_id)
        .where(Expense.deleted_at.is_(None))
    )
    if created_by is not None:
        base_query = base_query.where(Expense.created_by == created_by)

    # Count
    count_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result.scalar_one()

    # Paginated results
    offset = (page - 1) * page_size
    result = await db.execute(
        base_query
        .options(
            selectinload(Expense.payments),
            selectinload(Expense.splits),
        )
        .order_by(Expense.expense_date.desc(), Expense.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    expenses = list(result.scalars().unique().all())
    return expenses, total


async def update_expense(
    db: AsyncSession,
    expense: Expense,
    data: UpdateExpenseRequest,
) -> Expense:
    # Update scalar fields
    if data.description is not None:
        expense.description = data.description
    if data.currency is not None:
        expense.currency = data.currency
    if data.totalAmount is not None:
        expense.total_amount = data.totalAmount
    if data.expenseDate is not None:
        expense.expense_date = data.expenseDate
    if data.note is not None:
        expense.note = data.note

    # If payments or splits changed, rebuild everything atomically
    if data.paidBy is not None or data.splits is not None:
        # Validate totals if both provided
        if data.paidBy is not None and data.splits is not None:
            total_amount = data.totalAmount or expense.total_amount
            payer_total = sum(p.amount for p in data.paidBy)
            split_total = sum(s.amountOwed for s in data.splits)
            if abs(payer_total - total_amount) > Decimal("0.02"):
                raise HTTPException(
                    status_code=422,
                    detail=f"Payer amounts ({payer_total}) must sum to totalAmount ({total_amount})",
                )
            if abs(split_total - total_amount) > Decimal("0.02"):
                raise HTTPException(
                    status_code=422,
                    detail=f"Split amounts ({split_total}) must sum to totalAmount ({total_amount})",
                )

        # Delete old transfers linked to this expense
        await db.execute(
            delete(GroupTransfer).where(GroupTransfer.expense_id == expense.id)
        )

        # Delete old payments and splits
        await db.execute(
            delete(ExpensePayment).where(ExpensePayment.expense_id == expense.id)
        )
        await db.execute(
            delete(ExpenseSplit).where(ExpenseSplit.expense_id == expense.id)
        )
        await db.flush()

        payment_objects = []
        split_objects = []

        if data.paidBy is not None:
            for payer_input in data.paidBy:
                payment = ExpensePayment(
                    expense_id=expense.id,
                    payer_id=payer_input.userId,
                    amount=payer_input.amount,
                )
                db.add(payment)
                payment_objects.append(payment)
        else:
            # Re-load existing payments
            result = await db.execute(
                select(ExpensePayment).where(ExpensePayment.expense_id == expense.id)
            )
            payment_objects = list(result.scalars().all())

        if data.splits is not None:
            for split_input in data.splits:
                split = ExpenseSplit(
                    expense_id=expense.id,
                    user_id=split_input.userId,
                    amount_owed=split_input.amountOwed,
                    split_type=split_input.splitType,
                    shares=split_input.shares,
                    percentage=split_input.percentage,
                )
                db.add(split)
                split_objects.append(split)
        else:
            result = await db.execute(
                select(ExpenseSplit).where(ExpenseSplit.expense_id == expense.id)
            )
            split_objects = list(result.scalars().all())

        await db.flush()

        transfers = await _build_transfers_for_expense(
            expense_id=expense.id,
            group_id=expense.group_id,
            currency=expense.currency,
            payments=payment_objects,
            splits=split_objects,
        )
        for t in transfers:
            db.add(t)

    await db.commit()
    await db.refresh(expense)

    result = await db.execute(
        select(Expense)
        .where(Expense.id == expense.id)
        .options(
            selectinload(Expense.payments),
            selectinload(Expense.splits),
        )
    )
    return result.scalar_one()


async def delete_expense(db: AsyncSession, expense: Expense) -> None:
    # Delete GroupTransfer records for this expense
    await db.execute(
        delete(GroupTransfer).where(GroupTransfer.expense_id == expense.id)
    )
    # Soft delete
    expense.deleted_at = datetime.now(timezone.utc)
    await db.commit()
