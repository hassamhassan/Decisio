"""
Decisio — Authentication Module

JWT-based authentication with password hashing.
User types: admin, operator, engineer, viewer
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import bcrypt
from pydantic import BaseModel

# ── Configuration ───────────────────────────────────────────────────

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "decisio-secret-key-change-in-production-2024")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))  # 8 hours

# ── User types ──────────────────────────────────────────────────────
#
# super_admin: platform-wide superuser (no company scope)
# admin: company admin
# operator / engineer / viewer: standard company roles
# escalation_owner: specialist responsible for handling escalations

USER_TYPES = ["super_admin", "admin", "operator", "engineer", "viewer", "escalation_owner", "expert"]

# ── Password hashing ───────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against its bcrypt hash."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


# ── JWT tokens ──────────────────────────────────────────────────────

class TokenData(BaseModel):
    user_id: int
    username: str
    user_type: str
    company_id: Optional[int] = None  # None for super_admin


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> TokenData:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return TokenData(
            user_id=payload.get("user_id"),
            username=payload.get("username"),
            user_type=payload.get("user_type"),
            company_id=payload.get("company_id") if payload.get("company_id") is not None else None,
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── FastAPI dependencies ────────────────────────────────────────────

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[TokenData]:
    """Get the current authenticated user (returns None if no token)."""
    if not credentials:
        return None
    return decode_access_token(credentials.credentials)


async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> TokenData:
    """Require authentication — raises 401 if no valid token."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_access_token(credentials.credentials)


async def require_admin(
    user: TokenData = Depends(require_auth),
) -> TokenData:
    """Require admin or super_admin role — raises 403 otherwise.
    Company admins are scoped to their company_id; super_admin can act across companies.
    """
    if user.user_type not in ("admin", "super_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


async def require_company_admin(
    user: TokenData = Depends(require_admin),
) -> TokenData:
    """Require admin with a company (excludes super_admin for company-scoped operations).
    Use for admin routes that filter by company_id; super_admin should use Super Admin dashboard.
    """
    if user.company_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin has no company scope; use Super Admin dashboard.",
        )
    return user


async def require_super_admin(
    user: TokenData = Depends(require_auth),
) -> TokenData:
    """Require super_admin role — raises 403 if not super_admin.
    Only super_admin can create companies and create admin users for any company.
    """
    if user.user_type != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )
    return user
