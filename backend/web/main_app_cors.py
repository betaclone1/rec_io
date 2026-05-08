"""CORS allow_origins for main_app (host + prod domains + dev orderbook)."""

import os


def main_app_cors_allow_origins(host: str, main_app_port: int) -> list:
    explicit = [
        f"http://{host}:{main_app_port}",
        f"http://localhost:{main_app_port}",
        f"http://127.0.0.1:{main_app_port}",
        f"https://{host}:{main_app_port}",
        f"https://localhost:{main_app_port}",
        f"https://127.0.0.1:{main_app_port}",
        "https://rec-io.com",
        "https://www.rec-io.com",
        "http://rec-io.com",
        "http://www.rec-io.com",
    ]
    if os.getenv("REC_ENVIRONMENT") != "production":
        explicit.extend(
            [
                "http://127.0.0.1:8091",
                "http://localhost:8091",
            ]
        )
    if os.getenv("REC_ENVIRONMENT") == "production":
        return explicit
    return explicit + ["*"]
