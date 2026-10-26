import json
import logging
import uuid
from fastapi import Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("inventory-service")


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
