import os
from contextlib import asynccontextmanager
from http import HTTPStatus
import uvicorn
from fastapi import FastAPI

from src.utils.logger import get_logger
from src.api import sessions, auth, patients
from fastapi.staticfiles import StaticFiles

logger = get_logger()
logger.info("Service started successfully")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=== REGISTERED ROUTES ===")
    for r in app.routes:
        methods = ",".join(r.methods or [])
        print(f"{methods:10s} {r.path}")

    yield


app = FastAPI(lifespan=lifespan,
              title="Elbow Rehab Cloud API",)

app.mount("/auth", StaticFiles(directory="app/web/auth"), name="auth")
app.mount("/", StaticFiles(directory="app/web", html=True), name="static")

app.include_router(sessions.router)
app.include_router(auth.router)
app.include_router(patients.router)


@app.get("/health", status_code=HTTPStatus.OK)
def health():
    return {"message": "OK"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
