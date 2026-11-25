from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.routing import Route

from app.api import ws
from app.api.routers import all_routers
from app.mcp.server import mcp


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp.session_manager.run():
        yield


class _McpRoot:
    """Leitet exakt `/mcp` (ohne Slash) an die MCP-App weiter, damit kein Redirect auf `/mcp/` nötig ist."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        await self.inner({**scope, "path": "/", "root_path": scope.get("root_path", "") + "/mcp"}, receive, send)


app = FastAPI(title="dock", version="0.1.0", lifespan=lifespan)

for r in all_routers:
    app.include_router(r)
app.include_router(ws.router)

_mcp_app = mcp.streamable_http_app()
app.router.routes.append(Route("/mcp", _McpRoot(_mcp_app)))
app.mount("/mcp", _mcp_app)


@app.get("/api/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
