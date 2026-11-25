from fastapi import FastAPI

app = FastAPI(title="dock", version="0.1.0")


@app.get("/api/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
