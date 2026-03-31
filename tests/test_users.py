import uuid

import pytest
import pytest_asyncio
from fastapi import Depends
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.user import User
from tests.conftest import TestSessionLocal, make_user, override_get_db


_TEST_USER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


@pytest.fixture
def test_user():
    return make_user(
        user_id=_TEST_USER_ID,
        external_subject="user_test_001",
        email="alice@example.com",
        display_name="Alice",
    )


@pytest_asyncio.fixture
async def auth_client(test_user):
    """Client with auth overridden to return test_user fetched from the request db session."""
    async def mock_current_user(db: AsyncSession = Depends(get_db)):
        result = await db.execute(select(User).where(User.id == test_user.id))
        return result.scalar_one()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = mock_current_user

    from httpx import ASGITransport, AsyncClient as HxClient
    transport = ASGITransport(app=app)
    async with HxClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(autouse=True)
async def persist_test_user(test_user):
    """Persist the test user in the test DB before each test."""
    async with TestSessionLocal() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(type(test_user)).where(type(test_user).id == test_user.id)
        )
        if result.scalar_one_or_none() is None:
            session.add(test_user)
            await session.commit()


@pytest.mark.asyncio
async def test_get_me(auth_client, test_user):
    response = await auth_client.get("/users/me")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == test_user.email
    assert data["displayName"] == test_user.display_name
    assert data["emailVerified"] is True


@pytest.mark.asyncio
async def test_update_me(auth_client, test_user):
    response = await auth_client.patch(
        "/users/me",
        json={"displayName": "Alice Updated", "defaultCurrency": "EUR"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["displayName"] == "Alice Updated"
    assert data["defaultCurrency"] == "EUR"


@pytest.mark.asyncio
async def test_get_user_by_id(auth_client, test_user):
    response = await auth_client.get(f"/users/{test_user.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == test_user.email


@pytest.mark.asyncio
async def test_get_user_not_found(auth_client):
    random_id = uuid.uuid4()
    response = await auth_client.get(f"/users/{random_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_search_users(auth_client, test_user):
    response = await auth_client.get("/users/search", params={"q": "alice"})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_me_unauthenticated():
    """Without auth override, should get 401."""
    from httpx import ASGITransport, AsyncClient as HxClient
    transport = ASGITransport(app=app)
    async with HxClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/users/me")
    assert response.status_code == 401
