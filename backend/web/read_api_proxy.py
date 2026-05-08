import asyncio
import json
import logging
from typing import Any, Dict, Optional

import requests
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import Response


def read_api_forward_headers(request: Request) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    auth = request.headers.get("authorization")
    if auth:
        headers["Authorization"] = auth
    cookie = request.headers.get("cookie")
    if cookie:
        headers["Cookie"] = cookie
    return headers


def read_api_query_with_session(request: Request, base: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(base)
    for k in ("token", "user_id", "trading_mode"):
        v = request.query_params.get(k)
        if v is not None and str(v).strip() != "":
            out[k] = v
    return out


def synthetic_read_api_503() -> requests.Response:
    r = requests.Response()
    r.status_code = 503
    r.headers["Content-Type"] = "application/json"
    r._content = json.dumps({"detail": "read_api_temporarily_unavailable"}).encode("utf-8")
    r.encoding = "utf-8"
    return r


async def proxy_read_api_raw(
    request: Request,
    method: str,
    path: str,
    read_api_base_url: str,
    logger: logging.Logger,
    body: Optional[bytes] = None,
) -> requests.Response:
    url = f"{read_api_base_url}{path}"
    headers = read_api_forward_headers(request)
    if body is not None:
        headers["Content-Type"] = request.headers.get("content-type") or "application/json"

    def _do() -> requests.Response:
        if method.upper() == "GET":
            return requests.get(url, headers=headers, timeout=60)
        if method.upper() == "POST":
            return requests.post(url, data=body if body is not None else b"", headers=headers, timeout=60)
        if method.upper() == "PATCH":
            return requests.patch(url, data=body if body is not None else b"", headers=headers, timeout=60)
        raise ValueError(method)

    started = asyncio.get_running_loop().time()
    try:
        resp = await asyncio.to_thread(_do)
    except requests.RequestException as exc:
        logger.debug("read_api proxy transport error %s %s: %s", method, path, exc)
        return synthetic_read_api_503()
    finally:
        elapsed_ms = (asyncio.get_running_loop().time() - started) * 1000.0
        logger.info("read_api_proxy %s %s %.1fms", method.upper(), path, elapsed_ms)
    return resp


async def as_starlette_response(r: requests.Response) -> Response:
    ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    if r.status_code == 204 or not r.content:
        return Response(status_code=r.status_code)
    if "application/json" in ct:
        try:
            return JSONResponse(content=r.json(), status_code=r.status_code)
        except Exception:
            pass
    return Response(
        content=r.content,
        status_code=r.status_code,
        media_type=r.headers.get("content-type"),
    )
