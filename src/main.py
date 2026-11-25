import os
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api import auth, internal, patients, sessions
from src.api.v2 import sessions as sessions_v2
from src.root import ROOT_DIR
from src.utils.logger import get_logger

logger = get_logger()

WEB_DIR = Path(ROOT_DIR).parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    for route in app.routes:
        methods = ",".join(sorted(getattr(route, "methods", None) or []))
        logger.info("route %-10s %s", methods, route.path)
    logger.info("Service started successfully")
    yield


app = FastAPI(lifespan=lifespan, title="Elbow Rehab Cloud API")

# API routes first. Starlette matches routes in registration order, and a
# mount at "/" matches every path, so static files must be mounted last.
app.include_router(sessions_v2.router)
app.include_router(internal.router)
app.include_router(sessions.router)
app.include_router(auth.router)
app.include_router(patients.router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    # The default handler echoes the rejected input, which fails to serialize
    # for NaN/inf (-> 500). Report location and message only.
    errors = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    return JSONResponse(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, content={"detail": errors[:20]})


@app.get("/health", status_code=HTTPStatus.OK)
def health():
    return {"message": "OK"}


def mount_static_files(application: FastAPI, web_dir: Path = WEB_DIR) -> None:
    """Serve the web pages (doctor login/signup) from absolute paths."""
    if not (web_dir / "auth").is_dir():
        logger.warning("Static web directory %s not found; web pages are not served", web_dir)
        return
    application.mount("/auth", StaticFiles(directory=web_dir / "auth"), name="auth")
    application.mount("/", StaticFiles(directory=web_dir, html=True), name="static")


mount_static_files(app)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
