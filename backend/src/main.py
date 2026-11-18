from __future__ import annotations

from logging.config import dictConfig

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from src.admin.router import router as admin_router
from src.auth.router import router as auth_router
from src.claims.router import router as claims_router
from src.common.rate_limit import check_rate_limit
from src.core.config import get_settings
from src.core.db import SessionLocal
from src.core.errors import ApiError
from src.core.logging import JsonFormatter, new_request_id, request_id_var, setup_logging
from src.notifications.router import router as notifications_router
from src.offers.router import router as offers_router, retailer_router
from src.offers.saved_router import router as saved_offers_router
from src.referrals.router import router as referrals_router
from src.support.router import router as support_router
from src.todos.router import router as todos_router
from src.users.router import router as users_router
from src.wallet.router import router as wallet_router
from src.internal.router import router as internal_router

settings = get_settings()
setup_logging()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id_var.set(new_request_id())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id_var.get()
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(users_router, prefix="/api/v1")
    app.include_router(offers_router, prefix="/api/v1")
    app.include_router(saved_offers_router, prefix="/api/v1")
    app.include_router(retailer_router, prefix="/api/v1")
    app.include_router(claims_router, prefix="/api/v1")
    app.include_router(wallet_router, prefix="/api/v1")
    app.include_router(referrals_router, prefix="/api/v1")
    app.include_router(notifications_router, prefix="/api/v1")
    app.include_router(support_router, prefix="/api/v1")
    app.include_router(todos_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(internal_router, prefix="/api/v1")

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True}

    @app.get("/readyz", include_in_schema=False)
    def readyz():
        from sqlalchemy import text
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"ok": True}

    return app


app = create_app()
