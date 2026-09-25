from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.middleware.client_cache_middleware import ClientCacheMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/users/me")
    async def api_route() -> dict[str, str]:
        return {"ok": "api"}

    @app.get("/static-page")
    async def non_api_route() -> dict[str, str]:
        return {"ok": "page"}

    app.add_middleware(ClientCacheMiddleware, max_age=60)
    return app


class TestClientCacheMiddleware:
    def test_api_response_is_private_no_cache(self) -> None:
        client = TestClient(_build_app())

        response = client.get("/api/v1/users/me")

        assert response.headers["Cache-Control"] == "private, no-cache"

    def test_non_api_response_keeps_public_max_age(self) -> None:
        client = TestClient(_build_app())

        response = client.get("/static-page")

        assert response.headers["Cache-Control"] == "public, max-age=60"
