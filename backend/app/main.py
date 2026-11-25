from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.routing import Route

from app.api import ws
from app.api.routers import all_routers
from app.mcp.server import mcp


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Der Session-Manager von FastMCP lässt sich nur einmal starten. Pro Lifespan einen neuen anlegen,
    # damit z. B. mehrere `with TestClient(app)` in Tests funktionieren.
    mcp._session_manager = None
    mcp.streamable_http_app()
    async with mcp.session_manager.run():
        yield


class _McpEndpoint:
    """ASGI-Endpunkt für `/mcp` und `/mcp/…`: reicht an den aktuellen Session-Manager weiter (kein Redirect)."""

    async def __call__(self, scope, receive, send):
        await mcp.session_manager.handle_request(scope, receive, send)


app = FastAPI(title="dock", version="0.1.0", lifespan=lifespan)

for r in all_routers:
    app.include_router(r)
app.include_router(ws.router)

_mcp_endpoint = _McpEndpoint()
app.router.routes.append(Route("/mcp", _mcp_endpoint))
app.mount("/mcp", _mcp_endpoint)


@app.get("/api/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
