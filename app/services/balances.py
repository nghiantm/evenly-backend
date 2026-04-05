from collections import defaultdict
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.expense import GroupTransfer
from app.models.group import Group, GroupMember
from app.models.user import User
from app.schemas.balance import GroupBalanceResponse, MyBalancesResponse, PairwiseDebt, UserBalance


def _simplify_debts(
    net: dict[UUID, Decimal], currency: str
) -> list[PairwiseDebt]:
    """
    Greedy debt simplification: reduce N*(N-1)/2 pairwise debts to at most N-1
    transactions by matching the largest debtor against the largest creditor.
    Sort by (amount, str(uid)) for a stable, deterministic tiebreaker.
    """
    creditors: list[list] = sorted(
        [[uid, bal] for uid, bal in net.items() if bal > Decimal("0")],
        key=lambda x: (x[1], str(x[0])),
    )
    debtors: list[list] = sorted(
        [[uid, -bal] for uid, bal in net.items() if bal < Decimal("0")],
        key=lambda x: (x[1], str(x[0])),
    )

    result: list[PairwiseDebt] = []

    while creditors and debtors:
        creditor_uid, credit = creditors[-1]
        debtor_uid, debt = debtors[-1]

        settled = min(credit, debt)
        result.append(
            PairwiseDebt(
                fromUserId=debtor_uid,
                toUserId=creditor_uid,
                amount=settled.quantize(Decimal("0.01")),
                currency=currency,
            )
        )

        creditors[-1][1] -= settled
        debtors[-1][1] -= settled

        if creditors[-1][1] == Decimal("0"):
            creditors.pop()
        if debtors[-1][1] == Decimal("0"):
            debtors.pop()

    return result


async def get_group_balances(
    db: AsyncSession,
    group_id: UUID,
) -> GroupBalanceResponse:
    """
    Calculate balances from GroupTransfer records.
    from_user_id is debtor, to_user_id is creditor.
    Net for user X = SUM(amount where to_user=X) - SUM(amount where from_user=X)
    All transfers are stored in the group's defaultCurrency.
    """
    from app.models.group import Group
    group_result = await db.execute(select(Group).where(Group.id == group_id))
    group = group_result.scalar_one_or_none()
    currency = group.default_currency if group else "USD"

    result = await db.execute(
        select(GroupTransfer)
        .where(GroupTransfer.group_id == group_id)
    )
    transfers = result.scalars().all()

    # Fetch active members and their display names
    members_result = await db.execute(
        select(GroupMember, User)
        .join(User, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == group_id)
        .where(GroupMember.left_at.is_(None))
    )
    member_rows = members_result.all()
    user_names: dict[UUID, str] = {row.User.id: row.User.display_name for row in member_rows}

    # Net balance per user
    net: dict[UUID, Decimal] = defaultdict(Decimal)
    # Pairwise: (from_user, to_user) -> total owed
    pairwise: dict[tuple[UUID, UUID], Decimal] = defaultdict(Decimal)

    for transfer in transfers:
        net[transfer.to_user_id] += transfer.amount
        net[transfer.from_user_id] -= transfer.amount
        pairwise[(transfer.from_user_id, transfer.to_user_id)] += transfer.amount

    # Build user balance list (only active members)
    user_balances = [
        UserBalance(
            userId=uid,
            displayName=user_names.get(uid, str(uid)),
            netAmount=net.get(uid, Decimal("0")).quantize(Decimal("0.01")),
        )
        for uid in user_names
    ]

    # Net out direct A↔B pairs to get the baseline pairwise debts
    netted_pairwise: dict[tuple[UUID, UUID], Decimal] = {}
    visited: set[tuple[UUID, UUID]] = set()

    for (from_uid, to_uid), amount in pairwise.items():
        if (from_uid, to_uid) in visited or (to_uid, from_uid) in visited:
            continue
        reverse_amount = pairwise.get((to_uid, from_uid), Decimal("0"))
        net_amount = amount - reverse_amount
        if net_amount > Decimal("0"):
            netted_pairwise[(from_uid, to_uid)] = net_amount
        elif net_amount < Decimal("0"):
            netted_pairwise[(to_uid, from_uid)] = -net_amount
        visited.add((from_uid, to_uid))
        visited.add((to_uid, from_uid))

    unsimplified_count = sum(1 for amt in netted_pairwise.values() if amt > Decimal("0"))

    if group and group.simplify_debts:
        pairwise_debts = _simplify_debts(net, currency)
    else:
        pairwise_debts = [
            PairwiseDebt(
                fromUserId=from_uid,
                toUserId=to_uid,
                amount=amount.quantize(Decimal("0.01")),
                currency=currency,
            )
            for (from_uid, to_uid), amount in netted_pairwise.items()
            if amount > Decimal("0")
        ]

    transactions_saved = unsimplified_count - len(pairwise_debts)

    return GroupBalanceResponse(
        groupId=group_id,
        currency=currency,
        userBalances=user_balances,
        pairwiseDebts=pairwise_debts,
        transactionsSaved=transactions_saved,
    )


async def get_member_balance(
    db: AsyncSession,
    group_id: UUID,
    user_id: UUID,
) -> Decimal:
    """Return net balance for a specific user in a group (in group's defaultCurrency)."""
    result = await db.execute(
        select(GroupTransfer)
        .where(GroupTransfer.group_id == group_id)
        .where(
            (GroupTransfer.from_user_id == user_id)
            | (GroupTransfer.to_user_id == user_id)
        )
    )
    transfers = result.scalars().all()

    net = Decimal("0")
    for transfer in transfers:
        if transfer.to_user_id == user_id:
            net += transfer.amount
        if transfer.from_user_id == user_id:
            net -= transfer.amount

    return net.quantize(Decimal("0.01"))


async def get_my_balances(
    db: AsyncSession,
    user_id: UUID,
) -> MyBalancesResponse:
    """Aggregate balances across all groups for the current user."""
    # Get all active memberships
    memberships_result = await db.execute(
        select(GroupMember, Group)
        .join(Group, Group.id == GroupMember.group_id)
        .where(GroupMember.user_id == user_id)
        .where(GroupMember.left_at.is_(None))
    )
    memberships = memberships_result.all()

    group_ids = [row.Group.id for row in memberships]
    group_currency_map = {row.Group.id: row.Group.default_currency for row in memberships}
    group_name_map = {row.Group.id: row.Group.name for row in memberships}

    if not group_ids:
        return MyBalancesResponse(
            youOwe=Decimal("0"),
            youAreOwed=Decimal("0"),
            netByGroup=[],
            netByUser=[],
        )

    # Fetch all transfers involving this user across all groups
    transfers_result = await db.execute(
        select(GroupTransfer)
        .where(GroupTransfer.group_id.in_(group_ids))
        .where(
            (GroupTransfer.from_user_id == user_id)
            | (GroupTransfer.to_user_id == user_id)
        )
    )
    all_transfers = transfers_result.scalars().all()

    # Net per group — keyed by (group_id, currency)
    group_net: dict[tuple[UUID, str], Decimal] = defaultdict(Decimal)
    # Net per other user — keyed by (user_id, currency)
    user_net: dict[tuple[UUID, str], Decimal] = defaultdict(Decimal)

    you_owe = Decimal("0")
    you_are_owed = Decimal("0")

    for transfer in all_transfers:
        currency = transfer.currency
        if transfer.to_user_id == user_id:
            group_net[(transfer.group_id, currency)] += transfer.amount
            user_net[(transfer.from_user_id, currency)] += transfer.amount
        if transfer.from_user_id == user_id:
            group_net[(transfer.group_id, currency)] -= transfer.amount
            user_net[(transfer.to_user_id, currency)] -= transfer.amount

    for (gid, _currency), net in group_net.items():
        if net > Decimal("0"):
            you_are_owed += net
        else:
            you_owe += abs(net)

    # Fetch user display names for net_by_user
    other_user_ids = {uid for (uid, _) in user_net.keys()}
    user_display: dict[UUID, str] = {}
    if other_user_ids:
        users_result = await db.execute(
            select(User).where(User.id.in_(other_user_ids))
        )
        for u in users_result.scalars().all():
            user_display[u.id] = u.display_name

    net_by_group: list[dict[str, Any]] = [
        {
            "groupId": str(gid),
            "groupName": group_name_map.get(gid, str(gid)),
            "currency": currency,
            "netAmount": float(net.quantize(Decimal("0.01"))),
        }
        for (gid, currency), net in group_net.items()
    ]

    net_by_user: list[dict[str, Any]] = [
        {
            "userId": str(uid),
            "displayName": user_display.get(uid, str(uid)),
            "currency": currency,
            "netAmount": float(net.quantize(Decimal("0.01"))),
        }
        for (uid, currency), net in user_net.items()
        if net != Decimal("0")
    ]

    return MyBalancesResponse(
        youOwe=you_owe.quantize(Decimal("0.01")),
        youAreOwed=you_are_owed.quantize(Decimal("0.01")),
        netByGroup=net_by_group,
        netByUser=net_by_user,
    )


async def recalculate_group_balances(
    db: AsyncSession,
    group_id: UUID,
) -> None:
    """
    Rebuild all GroupTransfer records for a group from scratch
    by re-deriving from expenses and settlements.
    """
    from app.models.expense import Expense, ExpensePayment, ExpenseSplit
    from app.models.group import Group
    from app.models.settlement import Settlement
    from app.services.expenses import _build_transfers_for_expense
    from sqlalchemy import delete

    # Get group default currency
    group_result = await db.execute(select(Group).where(Group.id == group_id))
    group = group_result.scalar_one()
    group_default_currency = group.default_currency

    # Delete all existing transfers for this group
    await db.execute(
        delete(GroupTransfer).where(GroupTransfer.group_id == group_id)
    )
    await db.flush()

    # Re-create from active expenses
    expenses_result = await db.execute(
        select(Expense)
        .where(Expense.group_id == group_id)
        .where(Expense.deleted_at.is_(None))
    )
    expenses = expenses_result.scalars().all()

    for expense in expenses:
        payments_result = await db.execute(
            select(ExpensePayment).where(ExpensePayment.expense_id == expense.id)
        )
        payments = list(payments_result.scalars().all())

        splits_result = await db.execute(
            select(ExpenseSplit).where(ExpenseSplit.expense_id == expense.id)
        )
        splits = list(splits_result.scalars().all())

        exchange_rate = expense.exchange_rate if expense.exchange_rate is not None else Decimal("1")
        transfers = await _build_transfers_for_expense(
            expense_id=expense.id,
            group_id=group_id,
            transfer_currency=group_default_currency,
            exchange_rate=exchange_rate,
            payments=payments,
            splits=splits,
        )
        for t in transfers:
            db.add(t)

    # Re-create from settlements
    settlements_result = await db.execute(
        select(Settlement).where(Settlement.group_id == group_id)
    )
    settlements = settlements_result.scalars().all()

    for settlement in settlements:
        # Settlement: from_user paid to_user, so it reduces from_user's debt to to_user
        # Create a transfer from to_user -> from_user with negative effect
        # i.e., from_user is now the creditor for this transfer (offsets existing debt)
        transfer = GroupTransfer(
            group_id=group_id,
            settlement_id=settlement.id,
            from_user_id=settlement.to_user_id,
            to_user_id=settlement.from_user_id,
            currency=settlement.currency,
            amount=settlement.amount,
        )
        db.add(transfer)

    await db.commit()
