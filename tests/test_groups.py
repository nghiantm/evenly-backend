import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.security import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.group import Group, GroupMember
from tests.conftest import TestSessionLocal, make_user, override_get_db


_OWNER_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
_MEMBER_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


def make_owner():
    return make_user(
        user_id=_OWNER_ID,
        external_subject="owner_001",
        email="owner@example.com",
        display_name="Owner",
    )


@pytest_asyncio.fixture
async def owner_user():
    user = make_owner()
    async with TestSessionLocal() as session:
        result = await session.execute(
            select(type(user)).where(type(user).id == user.id)
        )
        if result.scalar_one_or_none() is None:
            session.add(user)
            await session.commit()
    return user


@pytest_asyncio.fixture
async def auth_client(owner_user):
    async def mock_current_user():
        return owner_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = mock_current_user

    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_group(auth_client, owner_user):
    response = await auth_client.post(
        "/groups",
        json={"name": "Trip to Paris", "defaultCurrency": "EUR"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Trip to Paris"
    assert data["defaultCurrency"] == "EUR"
    assert data["myRole"] == "OWNER"
    assert data["memberCount"] == 1


@pytest.mark.asyncio
async def test_list_groups(auth_client, owner_user):
    # Create a group first
    await auth_client.post(
        "/groups",
        json={"name": "Test Group List"},
    )
    response = await auth_client.get("/groups")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_get_group_detail(auth_client, owner_user):
    create_resp = await auth_client.post(
        "/groups",
        json={"name": "Detail Group"},
    )
    group_id = create_resp.json()["groupId"]

    response = await auth_client.get(f"/groups/{group_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["groupId"] == group_id
    assert "members" in data
    assert len(data["members"]) == 1
    assert data["members"][0]["role"] == "OWNER"


@pytest.mark.asyncio
async def test_update_group(auth_client, owner_user):
    create_resp = await auth_client.post("/groups", json={"name": "Old Name"})
    group_id = create_resp.json()["groupId"]

    response = await auth_client.patch(
        f"/groups/{group_id}",
        json={"name": "New Name", "simplifyDebts": True},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"
    assert response.json()["simplifyDebts"] is True


@pytest.mark.asyncio
async def test_get_group_not_found(auth_client):
    random_id = uuid.uuid4()
    response = await auth_client.get(f"/groups/{random_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_add_and_remove_member(auth_client, owner_user):
    # Create a second user
    second_user = make_user(
        user_id=_MEMBER_ID,
        external_subject="member_001",
        email="member001@example.com",
        display_name="Member One",
    )
    async with TestSessionLocal() as session:
        result = await session.execute(
            select(type(second_user)).where(type(second_user).id == second_user.id)
        )
        if result.scalar_one_or_none() is None:
            session.add(second_user)
            await session.commit()

    create_resp = await auth_client.post("/groups", json={"name": "Member Test Group"})
    group_id = create_resp.json()["groupId"]

    # Add member
    add_resp = await auth_client.post(
        f"/groups/{group_id}/members",
        json={"userId": str(second_user.id)},
    )
    assert add_resp.status_code == 201
    assert add_resp.json()["userId"] == str(second_user.id)
    assert add_resp.json()["role"] == "MEMBER"

    # Remove member
    remove_resp = await auth_client.delete(
        f"/groups/{group_id}/members/{second_user.id}"
    )
    assert remove_resp.status_code == 204


@pytest.mark.asyncio
async def test_archive_group(auth_client, owner_user):
    create_resp = await auth_client.post("/groups", json={"name": "To Be Archived"})
    group_id = create_resp.json()["groupId"]

    response = await auth_client.delete(f"/groups/{group_id}")
    assert response.status_code == 204

    # Verify archived_at is set by fetching the group
    detail_resp = await auth_client.get(f"/groups/{group_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["archivedAt"] is not None
