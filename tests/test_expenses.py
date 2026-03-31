import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.security import get_current_user
from app.db.session import get_db
from app.main import app
from tests.conftest import TestSessionLocal, make_user, override_get_db


_USER_A_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
_USER_B_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000002")


@pytest_asyncio.fixture
async def two_users():
    user_a = make_user(
        user_id=_USER_A_ID,
        external_subject="expense_user_a",
        email="expense_a@example.com",
        display_name="User A",
    )
    user_b = make_user(
        user_id=_USER_B_ID,
        external_subject="expense_user_b",
        email="expense_b@example.com",
        display_name="User B",
    )
    async with TestSessionLocal() as session:
        for u in (user_a, user_b):
            result = await session.execute(
                select(type(u)).where(type(u).id == u.id)
            )
            if result.scalar_one_or_none() is None:
                session.add(u)
        await session.commit()
    return user_a, user_b


@pytest_asyncio.fixture
async def group_with_two_members(two_users):
    """Create a group via HTTP with user_a as owner, then add user_b."""
    user_a, user_b = two_users

    async def mock_user_a():
        return user_a

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = mock_user_a

    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        create_resp = await ac.post("/groups", json={"name": "Expense Test Group"})
        assert create_resp.status_code == 201, create_resp.text
        group_id = create_resp.json()["groupId"]

        add_resp = await ac.post(
            f"/groups/{group_id}/members",
            json={"userId": str(user_b.id)},
        )
        assert add_resp.status_code == 201, add_resp.text

    return group_id, user_a, user_b


@pytest_asyncio.fixture
async def auth_client_a(two_users):
    user_a, _ = two_users

    async def mock_user_a():
        return user_a

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = mock_user_a

    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_expense(auth_client_a, group_with_two_members):
    group_id, user_a, user_b = group_with_two_members

    payload = {
        "groupId": group_id,
        "description": "Dinner",
        "currency": "USD",
        "totalAmount": "100.00",
        "expenseDate": str(date.today()),
        "paidBy": [{"userId": str(user_a.id), "amount": "100.00"}],
        "splits": [
            {"userId": str(user_a.id), "amountOwed": "50.00", "splitType": "EQUAL"},
            {"userId": str(user_b.id), "amountOwed": "50.00", "splitType": "EQUAL"},
        ],
    }
    response = await auth_client_a.post(f"/groups/{group_id}/expenses", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["description"] == "Dinner"
    assert data["totalAmount"] == "100.00"
    assert len(data["paidBy"]) == 1
    assert len(data["splits"]) == 2
    return data["expenseId"]


@pytest.mark.asyncio
async def test_list_expenses(auth_client_a, group_with_two_members):
    group_id, user_a, user_b = group_with_two_members

    # Create an expense first
    payload = {
        "groupId": group_id,
        "description": "Lunch",
        "currency": "USD",
        "totalAmount": "60.00",
        "expenseDate": str(date.today()),
        "paidBy": [{"userId": str(user_a.id), "amount": "60.00"}],
        "splits": [
            {"userId": str(user_a.id), "amountOwed": "30.00", "splitType": "EQUAL"},
            {"userId": str(user_b.id), "amountOwed": "30.00", "splitType": "EQUAL"},
        ],
    }
    await auth_client_a.post(f"/groups/{group_id}/expenses", json=payload)

    response = await auth_client_a.get(f"/groups/{group_id}/expenses")
    assert response.status_code == 200
    data = response.json()
    assert "expenses" in data
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_get_expense(auth_client_a, group_with_two_members):
    group_id, user_a, user_b = group_with_two_members

    payload = {
        "groupId": group_id,
        "description": "Coffee",
        "currency": "USD",
        "totalAmount": "20.00",
        "expenseDate": str(date.today()),
        "paidBy": [{"userId": str(user_a.id), "amount": "20.00"}],
        "splits": [
            {"userId": str(user_a.id), "amountOwed": "10.00", "splitType": "EXACT"},
            {"userId": str(user_b.id), "amountOwed": "10.00", "splitType": "EXACT"},
        ],
    }
    create_resp = await auth_client_a.post(f"/groups/{group_id}/expenses", json=payload)
    expense_id = create_resp.json()["expenseId"]

    response = await auth_client_a.get(f"/groups/{group_id}/expenses/{expense_id}")
    assert response.status_code == 200
    assert response.json()["expenseId"] == expense_id


@pytest.mark.asyncio
async def test_delete_expense(auth_client_a, group_with_two_members):
    group_id, user_a, user_b = group_with_two_members

    payload = {
        "groupId": group_id,
        "description": "To Delete",
        "currency": "USD",
        "totalAmount": "40.00",
        "expenseDate": str(date.today()),
        "paidBy": [{"userId": str(user_a.id), "amount": "40.00"}],
        "splits": [
            {"userId": str(user_a.id), "amountOwed": "20.00", "splitType": "EQUAL"},
            {"userId": str(user_b.id), "amountOwed": "20.00", "splitType": "EQUAL"},
        ],
    }
    create_resp = await auth_client_a.post(f"/groups/{group_id}/expenses", json=payload)
    expense_id = create_resp.json()["expenseId"]

    del_resp = await auth_client_a.delete(f"/groups/{group_id}/expenses/{expense_id}")
    assert del_resp.status_code == 204

    # Should return 404 now
    get_resp = await auth_client_a.get(f"/groups/{group_id}/expenses/{expense_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_expense_amount_validation(auth_client_a, group_with_two_members):
    """Payer amounts must sum to totalAmount."""
    group_id, user_a, user_b = group_with_two_members

    payload = {
        "groupId": group_id,
        "description": "Bad Amounts",
        "currency": "USD",
        "totalAmount": "100.00",
        "expenseDate": str(date.today()),
        "paidBy": [{"userId": str(user_a.id), "amount": "50.00"}],  # wrong: 50 != 100
        "splits": [
            {"userId": str(user_a.id), "amountOwed": "50.00", "splitType": "EQUAL"},
            {"userId": str(user_b.id), "amountOwed": "50.00", "splitType": "EQUAL"},
        ],
    }
    response = await auth_client_a.post(f"/groups/{group_id}/expenses", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_group_balances(auth_client_a, group_with_two_members):
    """After creating an expense, balances should reflect the debt."""
    group_id, user_a, user_b = group_with_two_members

    payload = {
        "groupId": group_id,
        "description": "Balance Test",
        "currency": "USD",
        "totalAmount": "100.00",
        "expenseDate": str(date.today()),
        "paidBy": [{"userId": str(user_a.id), "amount": "100.00"}],
        "splits": [
            {"userId": str(user_a.id), "amountOwed": "50.00", "splitType": "EQUAL"},
            {"userId": str(user_b.id), "amountOwed": "50.00", "splitType": "EQUAL"},
        ],
    }
    await auth_client_a.post(f"/groups/{group_id}/expenses", json=payload)

    balance_resp = await auth_client_a.get(f"/groups/{group_id}/balances")
    assert balance_resp.status_code == 200
    data = balance_resp.json()
    assert data["groupId"] == group_id
    assert "userBalances" in data
    assert "pairwiseDebts" in data

    # user_b owes user_a $50
    pairwise = data["pairwiseDebts"]
    assert len(pairwise) >= 1
    debt = next(
        (d for d in pairwise if d["fromUserId"] == str(user_b.id)),
        None,
    )
    assert debt is not None
    assert float(debt["amount"]) == pytest.approx(50.0, abs=0.05)
