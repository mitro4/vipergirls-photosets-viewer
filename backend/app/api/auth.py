"""Authentication endpoints: login, logout, status."""
from __future__ import annotations

from fastapi import APIRouter

from ..models import AuthStatus, LoginRequest
from ..scrapers.auth import (
    get_auth_status,
    login as do_login,
    logout as do_logout,
    md5_password,
)

router = APIRouter(tags=["auth"])


@router.get("/auth/status", response_model=AuthStatus)
async def status() -> AuthStatus:
    s = get_auth_status()
    return AuthStatus(logged_in=s["logged_in"], username=s["username"])


@router.post("/auth/login", response_model=AuthStatus)
async def login(body: LoginRequest) -> AuthStatus:
    pw_md5 = body.password_md5 or md5_password(body.password)
    await do_login(body.username, pw_md5)
    s = get_auth_status()
    return AuthStatus(logged_in=s["logged_in"], username=s["username"])


@router.post("/auth/logout", response_model=AuthStatus)
async def logout() -> AuthStatus:
    await do_logout()
    s = get_auth_status()
    return AuthStatus(logged_in=s["logged_in"], username=s["username"])
