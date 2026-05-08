"""Shared Cache-Control for tenant-sensitive JSON on main_app."""

from starlette.responses import Response


def apply_private_no_store_headers(response: Response) -> None:
    """Avoid stale browser/CDN cache of JSON that differs by trading_mode."""
    response.headers["Cache-Control"] = "private, no-store, max-age=0, must-revalidate"
    response.headers["Pragma"] = "no-cache"
