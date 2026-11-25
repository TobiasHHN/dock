"""WebSocket-Stub (Task 0.4): nimmt Verbindungen an und antwortet auf subscribe mit einem leeren Snapshot,
auf ops mit einem ack. Echte Implementierung: Task 1.5 (realtime/hub.py)."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def ws(socket: WebSocket):
    await socket.accept()
    try:
        while True:
            msg = await socket.receive_json()
            kind = msg.get("type")
            if kind == "subscribe":
                await socket.send_json({"type": "snapshot", "channel": msg["channel"], "seq": 0, "data": {}})
            elif kind == "ops":
                await socket.send_json({"type": "ack", "batch_id": msg["batch"]["batch_id"], "seq": {}, "results": {}})
    except WebSocketDisconnect:
        pass
