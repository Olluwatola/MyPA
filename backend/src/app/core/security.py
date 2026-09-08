import uuid as uuid_pkg
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

import bcrypt
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from ..crud.crud_token_blacklist import crud_token_blacklist
from ..crud.crud_users import crud_users
from ..schemas.token import TokenPayload
from ..schemas.token_blacklist import TokenBlacklistCreate
from .config import settings

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login")


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    correct_password: bool = bcrypt.checkpw(plain_password.encode(), hashed_password.encode())
    return correct_password


def get_password_hash(password: str) -> str:
    hashed_password: str = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    return hashed_password


async def authenticate_user(email: str, password: str, db: AsyncSession) -> dict[str, Any] | None:
    db_user = await crud_users.get(db=db, email=email)
    if not db_user:
        return None

    # OAuth-only user (never set a password) — 401 rather than passing None into verify_password.
    if not db_user["hashed_password"]:
        return None

    if not await verify_password(password, db_user["hashed_password"]):
        return None

    return db_user


def _encode(user_id: uuid_pkg.UUID, token_type: TokenType, expires_delta: timedelta) -> tuple[str, str]:
    jti = str(uuid_pkg.uuid4())
    expire = datetime.now(UTC) + expires_delta
    payload = {"sub": str(user_id), "jti": jti, "exp": expire, "type": token_type.value}
    encoded_jwt: str = jwt.encode(payload, SECRET_KEY.get_secret_value(), algorithm=ALGORITHM)
    return encoded_jwt, jti


async def create_access_token(user_id: uuid_pkg.UUID, expires_delta: timedelta | None = None) -> tuple[str, str]:
    """Returns (token, jti)."""
    return _encode(user_id, TokenType.ACCESS, expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))


async def create_refresh_token(user_id: uuid_pkg.UUID, expires_delta: timedelta | None = None) -> tuple[str, str]:
    """Returns (token, jti)."""
    return _encode(user_id, TokenType.REFRESH, expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))


async def verify_token(token: str, expected_token_type: TokenType, db: AsyncSession) -> TokenPayload | None:
    """Decode a JWT, check its type, and check it hasn't been blacklisted.

    The single choke point every protected route goes through.
    """
    try:
        raw_payload = jwt.decode(token, SECRET_KEY.get_secret_value(), algorithms=[ALGORITHM])
    except JWTError:
        return None

    try:
        payload = TokenPayload(**raw_payload)
    except (TypeError, ValueError):
        return None

    if payload.type != expected_token_type.value:
        return None

    is_blacklisted = await crud_token_blacklist.exists(db, jti=payload.jti)
    if is_blacklisted:
        return None

    return payload


async def blacklist_token(payload: TokenPayload, db: AsyncSession) -> None:
    already_blacklisted = await crud_token_blacklist.exists(db, jti=payload.jti)
    if already_blacklisted:
        return

    await crud_token_blacklist.create(
        db,
        object=TokenBlacklistCreate(
            jti=payload.jti,
            token_type=payload.type,
            expires_at=datetime.fromtimestamp(payload.exp, tz=UTC),
        ),
    )


def decode_token_ignoring_expiry(token: str) -> TokenPayload | None:
    """Decode a token's claims without rejecting an already-expired one — used at
    logout, where the goal is just to blacklist the `jti`, not to authorize anything."""
    try:
        raw_payload = jwt.decode(
            token, SECRET_KEY.get_secret_value(), algorithms=[ALGORITHM], options={"verify_exp": False}
        )
        return TokenPayload(**raw_payload)
    except (JWTError, TypeError, ValueError):
        return None
