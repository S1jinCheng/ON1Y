"""JWT auth middleware and route helpers for the FastAPI app."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from on1y.auth.context import get_current_user_id, set_current_user_id
from on1y.auth.tokens import create_access_token, decode_access_token
from on1y.config import get_settings
from on1y.user.accounts import UserRow, UserStore, user_public_dict

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

_PUBLIC_API_PREFIXES = (
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/status",
)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: str | None = None
    display_name: str | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=200)


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    query_token = request.query_params.get("access_token")
    if query_token:
        return str(query_token).strip()
    return request.cookies.get("on1y_token")


def register_auth_routes(app: Any) -> None:
    @app.get("/api/auth/status")
    def auth_status() -> dict[str, Any]:
        from on1y.adapters.sqlite_storage import get_storage

        settings = get_settings()
        storage = get_storage()
        try:
            store = UserStore(storage)
            return {
                "auth_required": settings.auth_required,
                "allow_registration": settings.auth_allow_registration,
                "multi_user": storage._current_schema_version(storage._connect()) >= 9,
                "user_count": store.count_users(),
            }
        finally:
            storage.close()

    @app.post("/api/auth/register")
    def auth_register(body: RegisterRequest) -> dict[str, Any]:
        settings = get_settings()
        if not settings.auth_allow_registration:
            raise HTTPException(status_code=403, detail="registration disabled")
        from on1y.adapters.sqlite_storage import get_storage

        storage = get_storage()
        try:
            store = UserStore(storage)
            if storage._current_schema_version(storage._connect()) < 9:
                raise HTTPException(status_code=503, detail="database migration required")
            user = store.create_user(
                username=body.username,
                password=body.password,
                email=body.email,
                display_name=body.display_name,
            )
            token = create_access_token(user_id=user.id, username=user.username)
            return {"token": token, "user": user_public_dict(user)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            storage.close()

    @app.post("/api/auth/login")
    def auth_login(body: LoginRequest) -> dict[str, Any]:
        from on1y.adapters.sqlite_storage import get_storage

        storage = get_storage()
        try:
            store = UserStore(storage)
            user = store.authenticate(body.username, body.password)
            if user is None:
                raise HTTPException(status_code=401, detail="invalid username or password")
            token = create_access_token(user_id=user.id, username=user.username)
            return {"token": token, "user": user_public_dict(user)}
        finally:
            storage.close()

    @app.get("/api/auth/me")
    def auth_me(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict[str, Any]:
        user = _resolve_user(credentials)
        if user is None:
            raise HTTPException(status_code=401, detail="not authenticated")
        return {"user": user_public_dict(user)}

    @app.post("/api/auth/logout")
    def auth_logout() -> dict[str, str]:
        return {"status": "ok"}

    @app.patch("/api/auth/profile")
    def auth_update_profile(body: UpdateProfileRequest) -> dict[str, Any]:
        uid = get_current_user_id()
        if uid is None:
            raise HTTPException(status_code=401, detail="not authenticated")
        from on1y.adapters.sqlite_storage import get_storage

        storage = get_storage()
        try:
            store = UserStore(storage)
            try:
                user = store.update_profile_fields(
                    uid,
                    display_name=body.display_name,
                    email=body.email,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"user": user_public_dict(user)}
        finally:
            storage.close()

    @app.patch("/api/auth/password")
    def auth_change_password(body: ChangePasswordRequest) -> dict[str, Any]:
        uid = get_current_user_id()
        if uid is None:
            raise HTTPException(status_code=401, detail="not authenticated")
        from on1y.adapters.sqlite_storage import get_storage

        storage = get_storage()
        try:
            store = UserStore(storage)
            if not store.verify_user_password(uid, body.current_password):
                raise HTTPException(status_code=400, detail="当前密码不正确")
            store.set_password_by_id(uid, body.new_password)
            return {"status": "ok"}
        finally:
            storage.close()


def _resolve_user(credentials: HTTPAuthorizationCredentials | None) -> UserRow | None:
    token = credentials.credentials if credentials else None
    if not token:
        uid = get_current_user_id()
        if uid is None:
            return None
        from on1y.adapters.sqlite_storage import get_storage

        storage = get_storage()
        try:
            return UserStore(storage).get_user_by_id(uid)
        finally:
            storage.close()
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
        username = str(payload.get("usr") or "")
    except Exception:
        return None
    from on1y.adapters.sqlite_storage import get_storage

    storage = get_storage()
    try:
        user = UserStore(storage).get_user_by_id(user_id)
        if user and user.username == username:
            return user
        return UserStore(storage).get_user_by_id(user_id)
    finally:
        storage.close()


def install_auth_middleware(app: Any) -> None:
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next: Any) -> Any:
        # Browsers send OPTIONS without Authorization; must not 401 or CORS preflight fails.
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        if any(path.startswith(prefix) for prefix in _PUBLIC_API_PREFIXES):
            return await call_next(request)

        settings = get_settings()
        if not settings.auth_required:
            set_current_user_id(1)
            try:
                return await call_next(request)
            finally:
                set_current_user_id(None)

        token = _extract_token(request)
        if not token:
            return JSONResponse(status_code=401, content={"detail": "authentication required"})

        try:
            payload = decode_access_token(token)
            user_id = int(payload["sub"])
        except Exception:
            return JSONResponse(status_code=401, content={"detail": "invalid or expired token"})

        set_current_user_id(user_id)
        try:
            return await call_next(request)
        finally:
            set_current_user_id(None)
