import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import get_settings
from .database import create_tables
from .logging_config import configure_logging, request_id_context
from . import models  # noqa: F401
from .routers import action_items, meetings, participants


configure_logging()
logger = logging.getLogger(__name__)


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(participants.router, prefix="/api")
app.include_router(meetings.router, prefix="/api")
app.include_router(action_items.router, prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    token = request_id_context.set(request_id)
    started = time.perf_counter()
    response = None
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "duration_ms": duration_ms,
            },
        )
        if response is not None:
            response.headers["X-Request-ID"] = request_id
        request_id_context.reset(token)


def error_response(request: Request, message: str, status_code: int) -> JSONResponse:
    request_id = getattr(request.state, "request_id", request_id_context.get())
    return JSONResponse(
        status_code=status_code,
        content={"error": "request_error", "message": message, "request_id": request_id},
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return error_response(request, str(exc.detail), exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return error_response(request, "Request validation failed", 422)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", request_id_context.get())
    token = request_id_context.set(request_id)
    try:
        logger.error("unhandled request error", exc_info=exc)
    finally:
        request_id_context.reset(token)
    return error_response(request, "Internal server error", 500)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
