from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from faker import Faker
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import Session
from uuid6 import uuid7

from src.app.core.config import settings
from src.app.main import app

DATABASE_URI = settings.POSTGRES_URI
DATABASE_PREFIX = settings.POSTGRES_SYNC_PREFIX

sync_engine = create_engine(DATABASE_PREFIX + DATABASE_URI)
local_session = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


fake = Faker()


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, Any, None]:
    with TestClient(app) as _client:
        yield _client
    app.dependency_overrides = {}
    sync_engine.dispose()


@pytest.fixture
def db() -> Generator[Session, Any, None]:
    session = local_session()
    yield session
    session.close()


def override_dependency(dependency: Callable[..., Any], mocked_response: Any) -> None:
    app.dependency_overrides[dependency] = lambda: mocked_response


@pytest.fixture
def mock_db():
    """Mock database session for unit tests."""
    return Mock(spec=AsyncSession)


@pytest.fixture
def mock_redis():
    """Mock Redis connection for unit tests."""
    mock_redis = Mock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock(return_value=True)
    mock_redis.ping = AsyncMock(return_value=True)
    return mock_redis


@pytest.fixture
def sample_user_data():
    """Generate sample user registration data for tests."""
    return {
        "first_name": fake.first_name(),
        "last_name": fake.last_name(),
        "email": fake.email(),
        "password": fake.password(length=12),
    }


@pytest.fixture
def sample_user_read():
    """Generate a sample UserRead object."""
    from src.app.schemas.user import UserRead

    return UserRead(
        id=uuid7(),
        first_name=fake.first_name(),
        last_name=fake.last_name(),
        email=fake.email(),
        timezone="UTC",
        is_superuser=False,
    )


@pytest.fixture
def current_user_dict():
    """Mock current user from the get_current_user dependency (a raw CRUD dict)."""
    return {
        "id": uuid7(),
        "email": fake.email(),
        "first_name": fake.first_name(),
        "last_name": fake.last_name(),
        "hashed_password": "hashed",
        "oauth_provider": None,
        "oauth_sub": None,
        "timezone": "UTC",
        "is_superuser": False,
    }


@pytest.fixture
def oauth_user_dict():
    """A Google-only user with no password set."""
    return {
        "id": uuid7(),
        "email": fake.email(),
        "first_name": fake.first_name(),
        "last_name": fake.last_name(),
        "hashed_password": None,
        "oauth_provider": "google",
        "oauth_sub": fake.uuid4(),
        "timezone": "UTC",
        "is_superuser": False,
    }
