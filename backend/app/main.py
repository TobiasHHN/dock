from fastapi import FastAPI

from app.api import ws
from app.api.routers import all_routers

app = FastAPI(title="dock", version="0.1.0")

for r in all_routers:
    app.include_router(r)
app.include_router(ws.router)


@app.get("/api/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
