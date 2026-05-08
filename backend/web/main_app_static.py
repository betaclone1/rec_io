"""Frontend static mounts with cache-busting response headers."""

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.util.paths import get_frontend_dir


class CacheBustingStaticFiles(StaticFiles):
    async def __call__(self, scope, receive, send):
        async def send_with_cache_busting(message):
            if message["type"] == "http.response.start":
                message["headers"].extend(
                    [
                        (b"cache-control", b"no-cache, no-store, must-revalidate"),
                        (b"pragma", b"no-cache"),
                        (b"expires", b"0"),
                    ]
                )
            await send(message)

        await super().__call__(scope, receive, send_with_cache_busting)


def mount_frontend_static(app: FastAPI) -> None:
    frontend_dir = get_frontend_dir()
    app.mount("/tabs", CacheBustingStaticFiles(directory=f"{frontend_dir}/tabs"), name="tabs")
    app.mount("/audio", CacheBustingStaticFiles(directory=f"{frontend_dir}/audio"), name="audio")
    app.mount("/js", CacheBustingStaticFiles(directory=f"{frontend_dir}/js"), name="js")
    app.mount("/images", CacheBustingStaticFiles(directory=f"{frontend_dir}/images"), name="images")
    app.mount("/styles", CacheBustingStaticFiles(directory=f"{frontend_dir}/styles"), name="styles")
    app.mount("/data", CacheBustingStaticFiles(directory=f"{frontend_dir}/data"), name="data")
    legal = os.path.join(frontend_dir, "legal")
    if os.path.isdir(legal):
        app.mount("/legal", CacheBustingStaticFiles(directory=legal), name="legal")
