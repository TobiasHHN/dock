"""Demo email/password authentication and signed JWT principals (Task 1.1)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_session
from app.schemas.common import Actor

_bearer = HTTPBearer(auto_error=False)
_JWT_ALGORITHM = "HS256"
_JWT_ISSUER = "dock"
_ACCESS_TOKEN_TTL = timedelta(hours=8)
_PASSWORD_SCHEME = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 310_000
ROLE_NAMES = {
    "einkauf": "Einkauf",
    "mitarbeiter": "Mitarbeiter",
    "chef": "Chef",
}


class CurrentUser(BaseModel):
    """Authenticated user and server-verified actor from a signed token."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    email: str
    roles: list[str]  # current role keys loaded from the database
    actor_type: Literal["user", "agent"] = "user"
    agent_id: str | None = None
    actor_name: str | None = None

    @property
    def actor(self) -> Actor:
        if self.actor_type == "agent" and self.agent_id:
            return Actor(type="agent", id=self.agent_id, on_behalf_of=self.id, name=self.actor_name)
        return Actor(type="user", id=self.id, name=self.name)


def hash_password(password: str) -> str:
    """Hash a password with a salted, stdlib PBKDF2 implementation."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS)
    return f"{_PASSWORD_SCHEME}${_PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash or len(password) > 1024:
        return False
    try:
        scheme, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        iterations = int(iterations_raw)
        if scheme != _PASSWORD_SCHEME or iterations < 100_000 or iterations > 2_000_000:
            return False
        salt = bytes.fromhex(salt_raw)
        expected = bytes.fromhex(digest_raw)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def create_access_token(
    user_id: str,
    roles: list[str],
    *,
    actor: Actor | None = None,
    now: datetime | None = None,
    ttl: timedelta | None = None,
) -> str:
    """Issue a user token, or an internal agent-on-behalf token.

    No request field or header is accepted as an actor. Agent claims can only
    enter tokens through this server-side helper; no public agent token issuer
    exists in the demo auth flow yet.
    """
    issued_at = now or datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "sub": user_id,
        "roles": roles,
        "typ": "access",
        "iss": _JWT_ISSUER,
        "iat": issued_at,
        "exp": issued_at + (ttl or _ACCESS_TOKEN_TTL),
    }
    if actor is not None:
        if actor.type != "agent" or actor.on_behalf_of != user_id or not actor.id.startswith("agt_"):
            raise ValueError("Agent token actor must be an agent acting on behalf of the subject")
        payload["act"] = {"type": "agent", "id": actor.id, "on_behalf_of": user_id}
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Ungültige oder abgelaufene Anmeldung",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _decode_token(token: str) -> tuple[str, str | None]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[_JWT_ALGORITHM],
            issuer=_JWT_ISSUER,
            options={"require": ["sub", "typ", "iat", "exp", "iss"]},
        )
        user_id = payload.get("sub")
        roles = payload.get("roles")
        if (
            not isinstance(user_id, str)
            or not user_id.startswith("usr_")
            or payload.get("typ") != "access"
            or not isinstance(roles, list)
            or any(not isinstance(role, str) for role in roles)
        ):
            raise _unauthorized()

        actor_claim = payload.get("act")
        if actor_claim is None:
            return user_id, None
        if not isinstance(actor_claim, dict):
            raise _unauthorized()
        agent_id = actor_claim.get("id")
        if (
            actor_claim.get("type") != "agent"
            or not isinstance(agent_id, str)
            or not agent_id.startswith("agt_")
            or actor_claim.get("on_behalf_of") != user_id
        ):
            raise _unauthorized()
        return user_id, agent_id
    except (jwt.PyJWTError, TypeError, ValueError):
        raise _unauthorized() from None


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
    session: AsyncSession = Depends(get_session),
) -> CurrentUser:
    """Resolve only a valid Bearer JWT to an active database user."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    user_id, agent_id = _decode_token(credentials.credentials)

    result = await session.execute(
        text(
            """SELECT u.id, u.name, u.email, u.active,
                      COALESCE(array_agg(r.key) FILTER (WHERE r.key IS NOT NULL), '{}') AS roles
               FROM users AS u
               LEFT JOIN member_roles AS mr ON mr.member_id = u.id AND mr.workspace_id = :workspace_id
               LEFT JOIN roles AS r ON r.id = mr.role_id AND r.workspace_id = :workspace_id
               WHERE u.id = :user_id
               GROUP BY u.id"""
        ),
        {"workspace_id": "ws_demo", "user_id": user_id},
    )
    row = result.mappings().first()
    if row is None or not row["active"]:
        raise _unauthorized()

    if agent_id is not None:
        agent_result = await session.execute(
            text("SELECT name, active FROM agents WHERE id = :agent_id AND workspace_id = :workspace_id"),
            {"agent_id": agent_id, "workspace_id": "ws_demo"},
        )
        agent = agent_result.mappings().first()
        if agent is None or not agent["active"]:
            raise _unauthorized()

    return CurrentUser(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        roles=list(row["roles"] or []),
        actor_type="agent" if agent_id else "user",
        agent_id=agent_id,
        actor_name=agent["name"] if agent_id else None,
    )


def require_role(*roles: str):
    async def dep(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
        if not set(roles) & set(user.roles):
            raise HTTPException(status_code=403, detail=f"Rolle {' oder '.join(roles)} erforderlich")
        return user

    return dep
