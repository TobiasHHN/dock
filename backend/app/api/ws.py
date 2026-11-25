"""WebSocket-Endpunkt `/ws` (T 2.7, L 7.3). Die Logik liegt in `realtime/hub.py`.

Anmeldung: JWT als Query-Parameter `?token=…` (Browser können im WebSocket keinen Header setzen) oder als
`Authorization: Bearer …`. Ohne gültiges Token schließt der Server mit Code 4401. Der Akteur kommt immer aus
dem Token, nie aus einer Nachricht.

Fehler bei Abonnements (kein Recht, unbekannter Kanal) kommen als `reject` mit `batch_id = "subscribe:<kanal>"`,
ungültige Nachrichten als `reject` mit der `batch_id` aus der Nachricht (sonst `"invalid"`).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import TypeAdapter, ValidationError

from app.auth import CurrentUser, current_user
from app.db import session as db
from app.realtime import hub
from app.schemas.common import ApiError
from app.schemas.ws import (ClientMessage, OpsMsg, PresenceMsg, RejectMsg, SubscribeMsg, UnsubscribeMsg)

router = APIRouter()
_MESSAGE = TypeAdapter(ClientMessage)
WS_UNAUTHORIZED = 4401


async def _authenticate(socket: WebSocket, token: str | None) -> CurrentUser | None:
    if token is None:
        header = socket.headers.get("authorization", "")
        scheme, _, value = header.partition(" ")
        token = value if scheme.lower() == "bearer" and value else None
    if not token:
        return None
    try:
        async with db.SessionLocal() as session:
            return await current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), session)
    except HTTPException:
        return None


@router.websocket("/ws")
async def ws(socket: WebSocket, token: str | None = Query(default=None)):
    await socket.accept()
    user = await _authenticate(socket, token)
    if user is None:
        await socket.close(code=WS_UNAUTHORIZED, reason="Ungültige oder abgelaufene Anmeldung")
        return
    conn = await hub.connect(socket, user)
    try:
        while True:
            raw = await socket.receive_json()
            try:
                msg = _MESSAGE.validate_python(raw)
            except ValidationError as exc:
                batch = raw.get("batch") if isinstance(raw, dict) else None
                batch_id = batch.get("batch_id") if isinstance(batch, dict) else None
                errors = {".".join(str(p) for p in e["loc"]): e["msg"] for e in exc.errors()}
                await conn.send(RejectMsg(batch_id=str(batch_id or "invalid"), error=ApiError(
                    code="VALIDATION", message="Ungültige Nachricht", details={"errors": errors})))
                continue
            if isinstance(msg, SubscribeMsg):
                await hub.subscribe(conn, msg.channel, msg.since)
            elif isinstance(msg, UnsubscribeMsg):
                await hub.unsubscribe(conn, msg.channel)
            elif isinstance(msg, OpsMsg):
                hub.submit_ops(conn, msg.batch)
            elif isinstance(msg, PresenceMsg):
                await hub.update_presence(conn, msg)
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(conn)
