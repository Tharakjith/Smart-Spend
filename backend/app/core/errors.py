import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.money import MoneyError

log = logging.getLogger("smartspend")


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or {}


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


def _body(request: Request, code: str, message: str, details=None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": getattr(request.state, "request_id", None),
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_mw(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        return JSONResponse(_body(request, exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(MoneyError)
    async def money_error(request: Request, exc: MoneyError):
        return JSONResponse(_body(request, "invalid_amount", str(exc)), status_code=422)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = [
            {"loc": [str(p) for p in e.get("loc", [])], "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse(_body(request, "validation_failed", "Request validation failed", {"errors": errors}), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse(_body(request, "http_error", str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(IntegrityError)
    async def integrity_error(request: Request, exc: IntegrityError):
        log.warning("Integrity error: %s", exc.orig)
        return JSONResponse(
            _body(request, "constraint_violation", "The change conflicts with existing data (constraint violation)."),
            status_code=409,
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("Unhandled error")
        return JSONResponse(_body(request, "internal_error", "An unexpected error occurred."), status_code=500)
