"""Shared DB access for backtest scripts.

**Local dev:** ``REC_IO_BACKTEST_DB=local`` — uses ``DB_*`` / ``REC_*`` from your environment
(plus repo ``.env`` loaded without overriding the shell).

**Production (default):** ``REC_IO_BACKTEST_DB=prod`` and ``REC_IO_BACKTEST_TRANSPORT=ssh`` (default)
opens an SSH tunnel to the server and reads DB user/password/name from the **remote** environment
the same way as ``access-prod-db`` (source ``/opt/rec_io_server/.env`` if present, then
``REC_DB_PASS`` / ``DB_PASSWORD`` / ``rec_io_password`` chain). No production password is required
in your local ``.env``.

**Direct TCP to prod:** ``REC_IO_BACKTEST_TRANSPORT=direct`` — requires
``REC_IO_BACKTEST_DB_HOST`` and a matching ``DB_PASSWORD`` / ``REC_DB_PASS`` locally.

Other: ``REC_IO_BACKTEST_QUIET=1``, ``REC_IO_BACKTEST_REMOTE_ENVFILE`` (default
``/opt/rec_io_server/.env``), ``REC_IO_BACKTEST_LOCAL_PORT`` (fixed local tunnel port, or 0 = pick free).
"""

from __future__ import annotations

import atexit
import json
import os
import shlex
import socket
import subprocess
import sys
import time


def project_root() -> str:
    # helpers/db.py -> helpers -> backtest -> scripts -> repo root
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _load_repo_dotenv() -> None:
    """Load repo-root ``.env`` if present; does not override variables already set in the shell."""
    path = os.path.join(project_root(), ".env")
    if not os.path.isfile(path):
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        _load_env_file_simple(path)
        return
    load_dotenv(path)


def _load_env_file_simple(path: str) -> None:
    """Best-effort ``KEY=value`` parsing when python-dotenv is not installed."""
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if not key or key in os.environ:
                    continue
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                    val = val[1:-1]
                os.environ[key] = val
    except OSError:
        return


def _backtest_db_mode() -> str:
    return (os.getenv("REC_IO_BACKTEST_DB") or "prod").strip().lower()


def _apply_backtest_db_target_direct() -> None:
    """Point ``DB_HOST`` / ``REC_DB_HOST`` at production for direct TCP (requires local password)."""
    host = (
        (os.getenv("REC_IO_BACKTEST_DB_HOST") or os.getenv("REC_IO_PRODUCTION_DB_HOST") or "")
        .strip()
    )
    if not host:
        raise RuntimeError(
            "REC_IO_BACKTEST_TRANSPORT=direct requires REC_IO_BACKTEST_DB_HOST or "
            "REC_IO_PRODUCTION_DB_HOST, and DB_PASSWORD / REC_DB_PASS for that database."
        )
    os.environ["DB_HOST"] = host
    os.environ["REC_DB_HOST"] = host
    if not os.getenv("REC_IO_BACKTEST_QUIET"):
        print(f"backtest: direct TCP to PostgreSQL host {host}", file=sys.stderr)


def _ssh_target() -> str:
    t = (os.getenv("REC_IO_BACKTEST_SSH") or "").strip()
    if t:
        return t
    host = (os.getenv("REC_IO_BACKTEST_DB_HOST") or os.getenv("REC_IO_PRODUCTION_DB_HOST") or "").strip()
    if host:
        user = (os.getenv("REC_IO_BACKTEST_SSH_USER") or "root").strip()
        return f"{user}@{host}"
    raise RuntimeError(
        "SSH transport requires REC_IO_BACKTEST_SSH (e.g. root@hostname) or "
        "REC_IO_BACKTEST_DB_HOST (optional REC_IO_BACKTEST_SSH_USER, default root)."
    )


def _remote_envfile() -> str:
    return (os.getenv("REC_IO_BACKTEST_REMOTE_ENVFILE") or "/opt/rec_io_server/.env").strip()


_tunnel_proc: subprocess.Popen | None = None
_tunnel_port: int | None = None
_tunnel_atexit_registered = False


def _cleanup_tunnel() -> None:
    global _tunnel_proc, _tunnel_port
    if _tunnel_proc is not None and _tunnel_proc.poll() is None:
        _tunnel_proc.terminate()
        try:
            _tunnel_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _tunnel_proc.kill()
    _tunnel_proc = None
    _tunnel_port = None


def _pick_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_tcp(host: str, port: int, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.08)
    raise TimeoutError(f"No listener on {host}:{port} within {timeout}s")


def _ensure_ssh_tunnel(ssh_target: str, remote_pg_port: int) -> int:
    global _tunnel_proc, _tunnel_port, _tunnel_atexit_registered
    if _tunnel_port is not None:
        return _tunnel_port
    lp = int(os.getenv("REC_IO_BACKTEST_LOCAL_PORT") or "0")
    if lp <= 0:
        lp = _pick_free_port()
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "ExitOnForwardFailure=yes",
        "-N",
        "-L",
        f"127.0.0.1:{lp}:127.0.0.1:{remote_pg_port}",
        ssh_target,
    ]
    _tunnel_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        _wait_for_tcp("127.0.0.1", lp)
    except Exception:
        err_b = b""
        if _tunnel_proc.stderr:
            try:
                err_b = _tunnel_proc.stderr.read()
            except OSError:
                pass
        if _tunnel_proc.poll() is None:
            _tunnel_proc.terminate()
        _tunnel_proc = None
        msg = err_b.decode(errors="replace").strip() or "ssh forward failed"
        raise RuntimeError(f"SSH tunnel to {ssh_target} failed: {msg}") from None

    _tunnel_port = lp
    if not _tunnel_atexit_registered:
        atexit.register(_cleanup_tunnel)
        _tunnel_atexit_registered = True
    if not os.getenv("REC_IO_BACKTEST_QUIET"):
        print(
            f"backtest: SSH tunnel 127.0.0.1:{lp} -> {ssh_target}:5432 (Postgres on server)",
            file=sys.stderr,
        )
    return lp


def _fetch_db_params_via_ssh(ssh_target: str) -> dict[str, str | int]:
    """Mirror access-prod-db credential resolution on the remote host."""
    envf = _remote_envfile()
    envf_q = shlex.quote(envf)
    py = (
        "import json,os;"
        'p=os.environ.get("REC_DB_PASS") or os.environ.get("DB_PASSWORD") or "rec_io_password";'
        'rp=int(os.environ.get("REC_DB_PORT") or os.environ.get("DB_PORT") or "5432");'
        'print(json.dumps({"user":os.environ.get("REC_DB_USER") or os.environ.get("DB_USER") or "rec_io_user",'
        '"database":os.environ.get("REC_DB_NAME") or os.environ.get("DB_NAME") or "rec_io_db",'
        '"password":p,"remote_pg_port":rp,'
        '"sslmode":os.environ.get("REC_DB_SSLMODE") or os.environ.get("DB_SSLMODE") or "disable"}))'
    )
    remote = f"set -a; test -f {envf_q} && . {envf_q}; set +a; python3 -c {shlex.quote(py)}"
    r = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=20",
            ssh_target,
            "bash",
            "-lc",
            remote,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(
            "SSH fetch of DB credentials failed (check SSH access and "
            f"{envf} on server): {r.stderr.strip() or r.stdout.strip()}"
        )
    out = (r.stdout or "").strip()
    line = out.splitlines()[-1] if out else ""
    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Bad JSON from server for DB params: {line!r}") from e
    return data


def _get_connection_via_ssh_tunnel():
    import psycopg2

    ssh_target = _ssh_target()
    params = _fetch_db_params_via_ssh(ssh_target)
    rpp = int(params.get("remote_pg_port") or 5432)
    lp = _ensure_ssh_tunnel(ssh_target, rpp)
    try:
        return psycopg2.connect(
            host="127.0.0.1",
            port=lp,
            user=str(params["user"]),
            password=str(params["password"]),
            dbname=str(params["database"]),
            sslmode=str(params.get("sslmode") or "disable"),
        )
    except Exception as e:
        raise RuntimeError(f"PostgreSQL via SSH tunnel failed: {e}") from e


def get_connection():
    root = project_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    _load_repo_dotenv()

    mode = _backtest_db_mode()
    if mode in ("local", "dev", "development"):
        from backend.core.config.database import get_postgresql_connection

        conn = get_postgresql_connection()
        if conn is None:
            raise RuntimeError(
                "Could not open PostgreSQL connection. Set DB_HOST, DB_NAME, DB_USER, DB_PASSWORD "
                "(or REC_DB_* equivalents)."
            )
        return conn

    if mode not in ("prod", "production"):
        raise ValueError(f"REC_IO_BACKTEST_DB={mode!r} is invalid; use prod (default) or local")

    transport = (os.getenv("REC_IO_BACKTEST_TRANSPORT") or "ssh").strip().lower()
    if transport == "ssh":
        return _get_connection_via_ssh_tunnel()
    if transport == "direct":
        _apply_backtest_db_target_direct()
        from backend.core.config.database import get_postgresql_connection

        conn = get_postgresql_connection()
        if conn is None:
            raise RuntimeError(
                "Could not open PostgreSQL connection (direct mode). "
                "Set DB_PASSWORD / REC_DB_PASS and REC_IO_BACKTEST_DB_HOST."
            )
        return conn

    raise ValueError(f"REC_IO_BACKTEST_TRANSPORT={transport!r} invalid; use ssh or direct")
