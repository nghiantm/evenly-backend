import time
from typing import Optional

import httpx
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db

_jwks_cache: dict = {"keys": None, "fetched_at": 0}
JWKS_CACHE_TTL = 3600

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


async def get_jwks() -> dict:
    now = time.time()
    if _jwks_cache["keys"] is None or now - _jwks_cache["fetched_at"] > JWKS_CACHE_TTL:
        async with httpx.AsyncClient() as client:
            resp = await client.get(settings.CLERK_JWKS_URL)
            resp.raise_for_status()
            _jwks_cache["keys"] = resp.json()
            _jwks_cache["fetched_at"] = now
    return _jwks_cache["keys"]


async def verify_clerk_token(token: str) -> dict:
    jwks = await get_jwks()
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        key = next((k for k in jwks["keys"] if k["kid"] == kid), None)
        if not key:
            raise HTTPException(status_code=401, detail="Invalid token key: no matching JWKS key found")
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            options={"verify_aud": False},
            issuer=settings.CLERK_ISSUER,
        )
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """FastAPI dependency that verifies Clerk JWT and upserts the local user."""
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    claims = await verify_clerk_token(token)
    print("Clerk JWT claims:", claims)

    external_subject: str = claims["sub"]
    email: str = claims.get("email", "")
    email_verified: bool = claims.get("email_verified", False)
    display_name: str = (
        claims.get("name")
        or claims.get("full_name")
        or (email.split("@")[0] if email else external_subject)
    )

    # Import here to avoid circular imports
    from app.services.users import get_or_create_user

    user = await get_or_create_user(
        db,
        external_subject=external_subject,
        email=email,
        display_name=display_name,
        email_verified=email_verified,
    )
    return user
