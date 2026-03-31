"""
Test configuration with in-memory SQLite and mocked Clerk auth.

Usage:
    pytest tests/

The `get_current_user` dependency is overridden in each test module via
`app.dependency_overrides` so no real JWT or database is needed.
"""
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User

# ---------------------------------------------------------------------------
# In-memory SQLite engine for tests
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
TestSessionLocal = async_sessionmaker(
    test_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables():
    """Create all tables once per test session."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional scope for each test."""
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Shared test user factories
# ---------------------------------------------------------------------------

def make_user(
    *,
    user_id: uuid.UUID | None = None,
    external_subject: str = "user_test_default",
    email: str = "testuser@example.com",
    display_name: str = "Test User",
    email_verified: bool = True,
) -> User:
    return User(
        id=user_id or uuid.uuid4(),
        external_subject=external_subject,
        email=email,
        display_name=display_name,
        email_verified=email_verified,
        status="ACTIVE",
        default_currency="USD",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Override get_db and get_current_user for test client
# ---------------------------------------------------------------------------

async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    """
    HTTP test client with DB override.
    Tests must further override get_current_user themselves.
    """
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
