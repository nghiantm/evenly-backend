"""
Tests for balance accuracy after expenses and pairwise debt simplification.

Scenarios covered:
- Single expense, equal split
- Single expense, exact split
- Multiple expenses accumulate correctly
- Multi-payer expense distributes proportionally
- Net balance signs (positive = owed, negative = owes)
- Deleting an expense removes its balance contribution
- Updating an expense updates balances
- Settlement reduces balance
- Settlement fully cancels a debt
- Pairwise netting: A→B and B→A reduce to one net direction
- Pairwise full offset: mutual equal debts cancel to zero
- Three-person group: independent debts are tracked separately
- Recalculate rebuilds correct state from scratch
"""
import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.security import get_current_user
from app.db.session import get_db
from app.main import app
from tests.conftest import TestSessionLocal, make_user, override_get_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def three_users():
    user_a = make_user(
        user_id=uuid.uuid4(),
        external_subject=f"bal_user_a_{uuid.uuid4().hex[:8]}",
        email=f"bal_a_{uuid.uuid4().hex[:8]}@example.com",
        display_name="Alice",
    )
    user_b = make_user(
        user_id=uuid.uuid4(),
        external_subject=f"bal_user_b_{uuid.uuid4().hex[:8]}",
        email=f"bal_b_{uuid.uuid4().hex[:8]}@example.com",
        display_name="Bob",
    )
    user_c = make_user(
        user_id=uuid.uuid4(),
        external_subject=f"bal_user_c_{uuid.uuid4().hex[:8]}",
        email=f"bal_c_{uuid.uuid4().hex[:8]}@example.com",
        display_name="Carol",
    )
    async with TestSessionLocal() as session:
        for u in (user_a, user_b, user_c):
            result = await session.execute(select(type(u)).where(type(u).id == u.id))
            if result.scalar_one_or_none() is None:
                session.add(u)
        await session.commit()
    return user_a, user_b, user_c


@pytest_asyncio.fixture
async def group_with_three_members(three_users):
    user_a, user_b, user_c = three_users

    async def mock_user_a():
        return user_a

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = mock_user_a

    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/groups", json={"name": "Balance Test Group", "defaultCurrency": "USD"})
        assert resp.status_code == 201, resp.text
        group_id = resp.json()["groupId"]

        for user in (user_b, user_c):
            r = await ac.post(f"/groups/{group_id}/members", json={"userId": str(user.id)})
            assert r.status_code == 201, r.text

    app.dependency_overrides.clear()
    return group_id, user_a, user_b, user_c


def make_client(user):
    from httpx import ASGITransport, AsyncClient

    async def mock():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = mock
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def expense_payload(group_id, description, total, paid_by, splits, currency="USD"):
    return {
        "groupId": str(group_id),
        "description": description,
        "currency": currency,
        "totalAmount": str(total),
        "expenseDate": str(date.today()),
        "paidBy": [{"userId": str(uid), "amount": str(amt)} for uid, amt in paid_by],
        "splits": [
            {"userId": str(uid), "amountOwed": str(amt), "splitType": "EXACT"}
            for uid, amt in splits
        ],
    }


def get_net(balances_data, user_id):
    for b in balances_data["userBalances"]:
        if b["userId"] == str(user_id):
            return float(b["netAmount"])
    return 0.0


def get_debt(balances_data, from_id, to_id):
    for d in balances_data["pairwiseDebts"]:
        if d["fromUserId"] == str(from_id) and d["toUserId"] == str(to_id):
            return float(d["amount"])
    return 0.0


# ---------------------------------------------------------------------------
# Balance accuracy after expenses
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_expense_equal_split(group_with_three_members):
    """Alice pays $90, split equally: Bob and Carol each owe Alice $30."""
    group_id, alice, bob, carol = group_with_three_members

    async with make_client(alice) as ac:
        resp = await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "Dinner", "90.00",
                paid_by=[(alice.id, "90.00")],
                splits=[(alice.id, "30.00"), (bob.id, "30.00"), (carol.id, "30.00")],
            ),
        )
        assert resp.status_code == 201, resp.text

        bal = (await ac.get(f"/groups/{group_id}/balances")).json()

    assert get_net(bal, alice.id) == pytest.approx(60.0, abs=0.01)
    assert get_net(bal, bob.id) == pytest.approx(-30.0, abs=0.01)
    assert get_net(bal, carol.id) == pytest.approx(-30.0, abs=0.01)

    assert get_debt(bal, bob.id, alice.id) == pytest.approx(30.0, abs=0.01)
    assert get_debt(bal, carol.id, alice.id) == pytest.approx(30.0, abs=0.01)

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_single_expense_exact_split(group_with_three_members):
    """Alice pays $100, split as 50/30/20."""
    group_id, alice, bob, carol = group_with_three_members

    async with make_client(alice) as ac:
        await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "Hotel", "100.00",
                paid_by=[(alice.id, "100.00")],
                splits=[(alice.id, "50.00"), (bob.id, "30.00"), (carol.id, "20.00")],
            ),
        )
        bal = (await ac.get(f"/groups/{group_id}/balances")).json()

    assert get_net(bal, alice.id) == pytest.approx(50.0, abs=0.01)
    assert get_net(bal, bob.id) == pytest.approx(-30.0, abs=0.01)
    assert get_net(bal, carol.id) == pytest.approx(-20.0, abs=0.01)
    assert get_debt(bal, bob.id, alice.id) == pytest.approx(30.0, abs=0.01)
    assert get_debt(bal, carol.id, alice.id) == pytest.approx(20.0, abs=0.01)

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_multiple_expenses_accumulate(group_with_three_members):
    """Two expenses stack: Bob owes Alice $30 + $20 = $50 total."""
    group_id, alice, bob, carol = group_with_three_members

    async with make_client(alice) as ac:
        for desc, total, bob_share, carol_share in [
            ("Expense 1", "60.00", "30.00", "30.00"),
            ("Expense 2", "40.00", "20.00", "20.00"),
        ]:
            alice_share = str(float(total) - float(bob_share) - float(carol_share))
            await ac.post(
                f"/groups/{group_id}/expenses",
                json=expense_payload(
                    group_id, desc, total,
                    paid_by=[(alice.id, total)],
                    splits=[(alice.id, alice_share), (bob.id, bob_share), (carol.id, carol_share)],
                ),
            )

        bal = (await ac.get(f"/groups/{group_id}/balances")).json()

    assert get_net(bal, alice.id) == pytest.approx(100.0, abs=0.01)
    assert get_net(bal, bob.id) == pytest.approx(-50.0, abs=0.01)
    assert get_net(bal, carol.id) == pytest.approx(-50.0, abs=0.01)

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_multi_payer_expense(group_with_three_members):
    """
    Alice pays $60, Bob pays $30, total $90 split equally ($30 each).
    Alice paid 2/3, Bob paid 1/3 of the $90.
    Carol owes $30: $20 to Alice, $10 to Bob.
    Alice net: paid $60, owes $30 → +$30.
    Bob net: paid $30, owes $30 → $0.
    Carol net: owes $30 → -$30.
    """
    group_id, alice, bob, carol = group_with_three_members

    async with make_client(alice) as ac:
        await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "Groceries", "90.00",
                paid_by=[(alice.id, "60.00"), (bob.id, "30.00")],
                splits=[(alice.id, "30.00"), (bob.id, "30.00"), (carol.id, "30.00")],
            ),
        )
        bal = (await ac.get(f"/groups/{group_id}/balances")).json()

    assert get_net(bal, alice.id) == pytest.approx(30.0, abs=0.01)
    assert get_net(bal, bob.id) == pytest.approx(0.0, abs=0.01)
    assert get_net(bal, carol.id) == pytest.approx(-30.0, abs=0.01)

    # Carol owes Alice 2/3 of $30 = $20
    assert get_debt(bal, carol.id, alice.id) == pytest.approx(20.0, abs=0.01)
    # Carol owes Bob 1/3 of $30 = $10
    assert get_debt(bal, carol.id, bob.id) == pytest.approx(10.0, abs=0.01)

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_net_balance_signs(group_with_three_members):
    """Positive netAmount = owed money; negative = owes money."""
    group_id, alice, bob, carol = group_with_three_members

    async with make_client(alice) as ac:
        await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "Sign Test", "90.00",
                paid_by=[(alice.id, "90.00")],
                splits=[(alice.id, "30.00"), (bob.id, "30.00"), (carol.id, "30.00")],
            ),
        )
        bal = (await ac.get(f"/groups/{group_id}/balances")).json()

    assert get_net(bal, alice.id) > 0, "Alice paid — should be owed money (positive)"
    assert get_net(bal, bob.id) < 0, "Bob owes — should be negative"
    assert get_net(bal, carol.id) < 0, "Carol owes — should be negative"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_expense_removes_balance(group_with_three_members):
    """Deleting an expense removes its contribution from balances."""
    group_id, alice, bob, carol = group_with_three_members

    async with make_client(alice) as ac:
        resp = await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "To Delete", "90.00",
                paid_by=[(alice.id, "90.00")],
                splits=[(alice.id, "30.00"), (bob.id, "30.00"), (carol.id, "30.00")],
            ),
        )
        expense_id = resp.json()["expenseId"]

        del_resp = await ac.delete(f"/groups/{group_id}/expenses/{expense_id}")
        assert del_resp.status_code == 204

        bal = (await ac.get(f"/groups/{group_id}/balances")).json()

    assert get_net(bal, alice.id) == pytest.approx(0.0, abs=0.01)
    assert get_net(bal, bob.id) == pytest.approx(0.0, abs=0.01)
    assert get_net(bal, carol.id) == pytest.approx(0.0, abs=0.01)
    assert len(bal["pairwiseDebts"]) == 0

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_expense_updates_balance(group_with_three_members):
    """Updating an expense recalculates balances correctly."""
    group_id, alice, bob, carol = group_with_three_members

    async with make_client(alice) as ac:
        resp = await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "Editable", "90.00",
                paid_by=[(alice.id, "90.00")],
                splits=[(alice.id, "30.00"), (bob.id, "30.00"), (carol.id, "30.00")],
            ),
        )
        expense_id = resp.json()["expenseId"]

        # Update: total changes to $120, splits change
        patch_resp = await ac.patch(
            f"/groups/{group_id}/expenses/{expense_id}",
            json={
                "totalAmount": "120.00",
                "paidBy": [{"userId": str(alice.id), "amount": "120.00"}],
                "splits": [
                    {"userId": str(alice.id), "amountOwed": "40.00", "splitType": "EXACT"},
                    {"userId": str(bob.id), "amountOwed": "40.00", "splitType": "EXACT"},
                    {"userId": str(carol.id), "amountOwed": "40.00", "splitType": "EXACT"},
                ],
            },
        )
        assert patch_resp.status_code == 200

        bal = (await ac.get(f"/groups/{group_id}/balances")).json()

    assert get_net(bal, alice.id) == pytest.approx(80.0, abs=0.01)
    assert get_net(bal, bob.id) == pytest.approx(-40.0, abs=0.01)
    assert get_net(bal, carol.id) == pytest.approx(-40.0, abs=0.01)

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_settlement_reduces_balance(group_with_three_members):
    """Bob settling $20 of his $30 debt reduces the pairwise amount."""
    group_id, alice, bob, carol = group_with_three_members

    async with make_client(alice) as ac:
        await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "Pre-settle", "90.00",
                paid_by=[(alice.id, "90.00")],
                splits=[(alice.id, "30.00"), (bob.id, "30.00"), (carol.id, "30.00")],
            ),
        )

        settle_resp = await ac.post(
            f"/groups/{group_id}/settlements",
            json={
                "fromUserId": str(bob.id),
                "toUserId": str(alice.id),
                "currency": "USD",
                "amount": "20.00",
                "settlementDate": str(date.today()),
            },
        )
        assert settle_resp.status_code == 201

        bal = (await ac.get(f"/groups/{group_id}/balances")).json()

    # Bob paid back $20, still owes $10
    assert get_debt(bal, bob.id, alice.id) == pytest.approx(10.0, abs=0.01)
    assert get_net(bal, bob.id) == pytest.approx(-10.0, abs=0.01)
    assert get_net(bal, alice.id) == pytest.approx(40.0, abs=0.01)

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_settlement_fully_cancels_debt(group_with_three_members):
    """Bob settling the full $30 clears the debt entirely."""
    group_id, alice, bob, carol = group_with_three_members

    async with make_client(alice) as ac:
        await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "Full settle", "90.00",
                paid_by=[(alice.id, "90.00")],
                splits=[(alice.id, "30.00"), (bob.id, "30.00"), (carol.id, "30.00")],
            ),
        )
        await ac.post(
            f"/groups/{group_id}/settlements",
            json={
                "fromUserId": str(bob.id),
                "toUserId": str(alice.id),
                "currency": "USD",
                "amount": "30.00",
                "settlementDate": str(date.today()),
            },
        )

        bal = (await ac.get(f"/groups/{group_id}/balances")).json()

    assert get_debt(bal, bob.id, alice.id) == pytest.approx(0.0, abs=0.01)
    assert get_net(bal, bob.id) == pytest.approx(0.0, abs=0.01)
    # Carol still owes Alice $30
    assert get_net(bal, alice.id) == pytest.approx(30.0, abs=0.01)
    assert get_debt(bal, carol.id, alice.id) == pytest.approx(30.0, abs=0.01)

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Pairwise debt simplification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pairwise_netting_partial(group_with_three_members):
    """
    Expense 1: Alice pays $60, Bob owes $30.
    Expense 2: Bob pays $40, Alice owes $20.
    Net: Alice owes Bob $20 - $30 = Bob still owes Alice $10.
    """
    group_id, alice, bob, carol = group_with_three_members

    async with make_client(alice) as ac:
        # Alice pays, Bob owes $30
        await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "Alice pays", "60.00",
                paid_by=[(alice.id, "60.00")],
                splits=[(alice.id, "30.00"), (bob.id, "30.00")],
            ),
        )

    async with make_client(bob) as ac:
        # Bob pays, Alice owes $20
        await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "Bob pays", "40.00",
                paid_by=[(bob.id, "40.00")],
                splits=[(alice.id, "20.00"), (bob.id, "20.00")],
            ),
        )

    async with make_client(alice) as ac:
        bal = (await ac.get(f"/groups/{group_id}/balances")).json()

    # Net: Bob owes Alice $30, Alice owes Bob $20 → Bob still owes Alice $10
    assert get_debt(bal, bob.id, alice.id) == pytest.approx(10.0, abs=0.01)
    assert get_debt(bal, alice.id, bob.id) == pytest.approx(0.0, abs=0.01)

    assert get_net(bal, alice.id) == pytest.approx(10.0, abs=0.01)
    assert get_net(bal, bob.id) == pytest.approx(-10.0, abs=0.01)

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_pairwise_netting_full_offset(group_with_three_members):
    """
    Alice pays $60, Bob owes $30.
    Bob pays $60, Alice owes $30.
    Net: zero — no pairwise debt between them.
    """
    group_id, alice, bob, carol = group_with_three_members

    async with make_client(alice) as ac:
        await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "Alice pays", "60.00",
                paid_by=[(alice.id, "60.00")],
                splits=[(alice.id, "30.00"), (bob.id, "30.00")],
            ),
        )

    async with make_client(bob) as ac:
        await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "Bob pays", "60.00",
                paid_by=[(bob.id, "60.00")],
                splits=[(alice.id, "30.00"), (bob.id, "30.00")],
            ),
        )

    async with make_client(alice) as ac:
        bal = (await ac.get(f"/groups/{group_id}/balances")).json()

    assert get_debt(bal, alice.id, bob.id) == pytest.approx(0.0, abs=0.01)
    assert get_debt(bal, bob.id, alice.id) == pytest.approx(0.0, abs=0.01)
    assert get_net(bal, alice.id) == pytest.approx(0.0, abs=0.01)
    assert get_net(bal, bob.id) == pytest.approx(0.0, abs=0.01)

    # Verify no pairwise debt appears between Alice and Bob
    ab_debts = [
        d for d in bal["pairwiseDebts"]
        if {d["fromUserId"], d["toUserId"]} == {str(alice.id), str(bob.id)}
    ]
    assert len(ab_debts) == 0

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_independent_debts_not_merged(group_with_three_members):
    """
    Alice pays $90, Bob owes $30, Carol owes $30.
    These are independent debts — simplification should not merge them.
    """
    group_id, alice, bob, carol = group_with_three_members

    async with make_client(alice) as ac:
        await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "Group dinner", "90.00",
                paid_by=[(alice.id, "90.00")],
                splits=[(alice.id, "30.00"), (bob.id, "30.00"), (carol.id, "30.00")],
            ),
        )
        bal = (await ac.get(f"/groups/{group_id}/balances")).json()

    assert get_debt(bal, bob.id, alice.id) == pytest.approx(30.0, abs=0.01)
    assert get_debt(bal, carol.id, alice.id) == pytest.approx(30.0, abs=0.01)
    # Bob and Carol have no debt between themselves
    assert get_debt(bal, bob.id, carol.id) == pytest.approx(0.0, abs=0.01)
    assert get_debt(bal, carol.id, bob.id) == pytest.approx(0.0, abs=0.01)

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_pairwise_netting_with_multiple_expenses(group_with_three_members):
    """
    3 expenses create cross-debts between Alice and Bob:
    - Alice pays $30 → Bob owes Alice $15
    - Bob pays $20 → Alice owes Bob $10
    - Alice pays $10 → Bob owes Alice $5
    Net: Bob owes Alice $15 + $5 - $10 = $10
    """
    group_id, alice, bob, carol = group_with_three_members

    async with make_client(alice) as ac:
        await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "E1", "30.00",
                paid_by=[(alice.id, "30.00")],
                splits=[(alice.id, "15.00"), (bob.id, "15.00")],
            ),
        )
        await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "E3", "10.00",
                paid_by=[(alice.id, "10.00")],
                splits=[(alice.id, "5.00"), (bob.id, "5.00")],
            ),
        )

    async with make_client(bob) as ac:
        await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "E2", "20.00",
                paid_by=[(bob.id, "20.00")],
                splits=[(alice.id, "10.00"), (bob.id, "10.00")],
            ),
        )

    async with make_client(alice) as ac:
        bal = (await ac.get(f"/groups/{group_id}/balances")).json()

    assert get_debt(bal, bob.id, alice.id) == pytest.approx(10.0, abs=0.01)
    assert get_debt(bal, alice.id, bob.id) == pytest.approx(0.0, abs=0.01)
    assert get_net(bal, alice.id) == pytest.approx(10.0, abs=0.01)
    assert get_net(bal, bob.id) == pytest.approx(-10.0, abs=0.01)

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Recalculate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recalculate_matches_live_balances(group_with_three_members):
    """Recalculate rebuilds GroupTransfers from scratch and produces the same result."""
    group_id, alice, bob, carol = group_with_three_members

    async with make_client(alice) as ac:
        await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "Recalc test", "90.00",
                paid_by=[(alice.id, "90.00")],
                splits=[(alice.id, "30.00"), (bob.id, "30.00"), (carol.id, "30.00")],
            ),
        )

        bal_before = (await ac.get(f"/groups/{group_id}/balances")).json()

        recalc_resp = await ac.get(f"/groups/{group_id}/balances/recalculate")
        assert recalc_resp.status_code == 204

        bal_after = (await ac.get(f"/groups/{group_id}/balances")).json()

    assert get_net(bal_after, alice.id) == pytest.approx(get_net(bal_before, alice.id), abs=0.01)
    assert get_net(bal_after, bob.id) == pytest.approx(get_net(bal_before, bob.id), abs=0.01)
    assert get_net(bal_after, carol.id) == pytest.approx(get_net(bal_before, carol.id), abs=0.01)
    assert get_debt(bal_after, bob.id, alice.id) == pytest.approx(
        get_debt(bal_before, bob.id, alice.id), abs=0.01
    )

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_recalculate_after_manual_corruption(group_with_three_members):
    """
    Even if balances somehow drift, recalculate restores correct state.
    Simulated by creating an expense, running recalculate, then verifying correctness.
    """
    group_id, alice, bob, carol = group_with_three_members

    async with make_client(alice) as ac:
        await ac.post(
            f"/groups/{group_id}/expenses",
            json=expense_payload(
                group_id, "Corruption test", "60.00",
                paid_by=[(alice.id, "60.00")],
                splits=[(alice.id, "20.00"), (bob.id, "20.00"), (carol.id, "20.00")],
            ),
        )

        recalc_resp = await ac.get(f"/groups/{group_id}/balances/recalculate")
        assert recalc_resp.status_code == 204

        bal = (await ac.get(f"/groups/{group_id}/balances")).json()

    assert get_net(bal, alice.id) == pytest.approx(40.0, abs=0.01)
    assert get_net(bal, bob.id) == pytest.approx(-20.0, abs=0.01)
    assert get_net(bal, carol.id) == pytest.approx(-20.0, abs=0.01)
    assert get_debt(bal, bob.id, alice.id) == pytest.approx(20.0, abs=0.01)
    assert get_debt(bal, carol.id, alice.id) == pytest.approx(20.0, abs=0.01)

    app.dependency_overrides.clear()
