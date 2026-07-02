from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import BASE_DIR, settings
from .database import init_db
from .routers import account_routes, auth_routes, log_routes, settings_routes, task_routes


app = FastAPI(title="outlook-k12-imap", version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    init_db()


app.include_router(auth_routes.router)
app.include_router(account_routes.router)
app.include_router(task_routes.router)
app.include_router(log_routes.router)
app.include_router(settings_routes.router)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "index.html")


if __name__ == "__main__":
    server = settings["server"]
    uvicorn.run("app.main:app", host=server["host"], port=int(server["port"]), reload=False)

