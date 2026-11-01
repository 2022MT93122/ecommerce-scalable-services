import json
import logging
import uuid
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("order-service")


def setup(app):
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        rid = (
            request.headers.get("X-Request-ID")
            or request.headers.get("X-Correlation-ID")
            or str(uuid.uuid4())
        )
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Correlation-ID"] = rid
        logger.info(
            json.dumps(
                {
                    "event": "http",
                    "request_id": rid,
                    "path": request.url.path,
                    "method": request.method,
                    "status": response.status_code,
                }
            )
        )
        return response

    @app.exception_handler(ValueError)
    async def business_error(request: Request, exc: ValueError):
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "BUSINESS_CONFLICT",
                    "message": str(exc),
                },
                "request_id": getattr(request.state, "request_id", ""),
            },
        )

    def error(request, status, code, message):
        return JSONResponse(status_code=status, content={
            "error": {"code": code, "message": message},
            "request_id": getattr(request.state, "request_id", "")})

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            detail = exc.detail["error"]
            return error(request, exc.status_code, detail["code"], detail["message"])
        return error(request, exc.status_code, f"HTTP_{exc.status_code}", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        message = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return error(request, 422, "VALIDATION_ERROR", message)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        logger.exception(json.dumps({"event": "unhandled_error", "request_id": request.state.request_id}))
        response = error(request, 500, "INTERNAL_ERROR", "Internal service error")
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Correlation-ID"] = request.state.request_id
        return response
