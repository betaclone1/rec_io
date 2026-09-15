"""
Cycle reconstruction job/package API for the main web UI.

Local analysis only: hard-disabled when REC_ENVIRONMENT=production.
Requires master_admin. Does not mutate live trading, Redis, or production DB.

UI times are Eastern wall; backend converts to UTC before reconstruction.
Default trade source is the session tenant Postgres trade log.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from backend.core.tenant_context import resolved_tenant_user_no_for_app
from backend.util.paths import get_project_root
from backend.web.auth_routes import _session_is_master_admin

cycle_recon_router = APIRouter(tags=["cycle_recon"])

_JOBS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()
_ROOT = Path(get_project_root())


class RunBody(BaseModel):
    range_preset: Optional[str] = None  # 24h | 7d | 30d | all
    start_et: Optional[str] = None  # Eastern wall
    end_et: Optional[str] = None
    start: Optional[str] = None  # UTC ISO (legacy/advanced)
    end: Optional[str] = None
    symbols: List[str] = Field(default_factory=list)
    tickers: List[str] = Field(default_factory=list)
    trade_ids: List[str] = Field(default_factory=list)
    monitors: List[str] = Field(default_factory=list)
    trade_log: Optional[str] = None  # optional CSV override
    use_pg: bool = True
    user_no: Optional[str] = None
    workers: int = 1
    force_refresh: bool = False
    offline: bool = False
    export_csv: bool = False


def _runs_root() -> Path:
    from backend.core.cycle_recon.package_writer import default_runs_root

    return default_runs_root()


def _sanitize_text(s: str, *, limit: int = 4000) -> str:
    if not s:
        return ""
    cleaned = "".join(ch if (ch == "\n" or ch == "\t" or ord(ch) >= 32) else "?" for ch in s)
    return cleaned[-limit:]


def _jobs_dir() -> Path:
    d = _runs_root() / ".jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _job_meta_path(job_id: str) -> Path:
    return _jobs_dir() / f"{job_id}.json"


def _job_log_path(job_id: str) -> Path:
    return _jobs_dir() / f"{job_id}.log"


def _write_job_meta(job: Dict[str, Any]) -> None:
    p = _job_meta_path(str(job["job_id"]))
    payload = {k: v for k, v in job.items() if k != "cmd" or True}
    # cmd can be long; keep it
    try:
        p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def _read_job_meta(job_id: str) -> Optional[Dict[str, Any]]:
    p = _job_meta_path(job_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _kill_job_process(pid: Optional[int]) -> Dict[str, Any]:
    """SIGTERM then SIGKILL; prefer process-group kill when started with start_new_session."""
    if not pid:
        return {"killed": False, "reason": "no_pid"}
    pid_i = int(pid)
    errors: List[str] = []

    def _sig(sig: int) -> None:
        try:
            os.killpg(pid_i, sig)
            return
        except Exception:
            pass
        try:
            os.kill(pid_i, sig)
        except ProcessLookupError:
            pass
        except Exception as e:
            errors.append(str(e))

    _sig(15)
    time.sleep(0.4)
    if _pid_alive(pid_i):
        _sig(9)
        time.sleep(0.2)
    return {"killed": not _pid_alive(pid_i), "pid": pid_i, "errors": errors}


def _abandon_partial(run_id: str) -> Optional[str]:
    """Rename ``{run_id}.partial`` so it no longer looks like an active job."""
    if not run_id:
        return None
    partial = _runs_root() / f"{run_id}.partial"
    if not partial.is_dir():
        return None
    dest = _runs_root() / f"{run_id}.cancelled.{int(time.time())}"
    try:
        partial.rename(dest)
        return str(dest)
    except Exception:
        return None


def _mark_job_finished(job: Dict[str, Any], status: str, *, note: Optional[str] = None) -> Dict[str, Any]:
    job = dict(job)
    job["status"] = status
    job["finished_at"] = time.time()
    if note:
        prev = str(job.get("stderr_tail") or "")
        job["stderr_tail"] = (prev + "\n" + note).strip() if prev else note
    jid = str(job.get("job_id") or "")
    with _LOCK:
        if jid and jid in _JOBS:
            _JOBS[jid].update(job)
            _write_job_meta(_JOBS[jid])
        elif jid:
            _write_job_meta(job)
    return job


def _partial_progress(run_id: str) -> Dict[str, Any]:
    root = _runs_root()
    partial = root / f"{run_id}.partial"
    final = root / run_id
    target = partial if partial.is_dir() else (final if final.is_dir() else None)
    if target is None:
        return {"phase": "starting", "partial": False, "bytes": 0, "files": []}
    files = []
    total = 0
    for f in sorted(target.iterdir()):
        if not f.is_file() or f.name.startswith("."):
            continue
        sz = f.stat().st_size
        total += sz
        files.append({"name": f.name, "bytes": sz})
    return {
        "phase": "writing" if partial.is_dir() else "complete_dir",
        "partial": partial.is_dir(),
        "path": str(target),
        "bytes": total,
        "files": files[-12:],
        "file_count": len(files),
    }


def _enrich_job(job: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(job)
    started = float(out.get("started_at") or 0)
    finished = out.get("finished_at")
    now = time.time()
    out["elapsed_s"] = round((float(finished) if finished else now) - started, 1) if started else None
    out["pid_alive"] = _pid_alive(out.get("pid"))
    run_id = str(out.get("run_id") or "")
    out["progress"] = _partial_progress(run_id) if run_id else {}
    log_p = _job_log_path(str(out.get("job_id") or ""))
    if log_p.is_file():
        try:
            text = log_p.read_text(encoding="utf-8", errors="replace")
            out["log_tail"] = _sanitize_text(text, limit=6000)
        except Exception:
            out["log_tail"] = ""
    else:
        out["log_tail"] = _sanitize_text(
            str(out.get("stderr_tail") or "") + "\n" + str(out.get("stdout_tail") or "")
        )
    # Dead process must not stay "running" forever because a .partial dir remains
    if out.get("status") in ("running", "cancel_requested") and not out["pid_alive"]:
        final = (_runs_root() / run_id).is_dir() if run_id else False
        if final:
            reconciled = "done"
        elif out.get("status") == "cancel_requested":
            reconciled = "cancelled"
        else:
            reconciled = "error"
        out["status"] = reconciled
        out["finished_at"] = out.get("finished_at") or now
        # Persist so list_jobs stops treating this as active
        try:
            _mark_job_finished(out, reconciled)
        except Exception:
            pass
        if reconciled == "error" and not out.get("stderr_tail") and out.get("log_tail"):
            out["stderr_tail"] = out["log_tail"]
    out["stdout_tail"] = _sanitize_text(str(out.get("stdout_tail") or ""))
    out["stderr_tail"] = _sanitize_text(str(out.get("stderr_tail") or ""))
    return out


def _load_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job:
            return dict(job)
    return _read_job_meta(job_id)


def _gate() -> JSONResponse | None:
    if (os.getenv("REC_ENVIRONMENT") or "").strip().lower() == "production":
        return JSONResponse(
            status_code=403,
            content={
                "error": "cycle_recon is disabled in production",
                "detail": "Local offline analysis only; use a local checkout.",
            },
        )
    u = resolved_tenant_user_no_for_app()
    if not _session_is_master_admin(u):
        return JSONResponse(status_code=403, content={"error": "Forbidden — master_admin required"})
    return None


def _session_slot() -> str:
    u = resolved_tenant_user_no_for_app() or ""
    s = str(u).strip()
    if s.startswith("users_"):
        s = s[6:]
    if s.isdigit():
        return f"{int(s):04d}"
    return "0001"


def _bounds_for_catalog(range_preset: Optional[str], start_et: Optional[str], end_et: Optional[str]):
    from backend.core.cycle_recon.time_util import (
        et_date_str,
        parse_et_wall,
        range_preset_et_bounds,
    )

    if range_preset:
        start, end = range_preset_et_bounds(range_preset)
    else:
        start = parse_et_wall(start_et) if start_et else None
        end = parse_et_wall(end_et) if end_et else None
    return (
        et_date_str(start) if start else None,
        et_date_str(end) if end else None,
        start,
        end,
    )


@cycle_recon_router.get("/api/cycle_recon/health")
def health():
    denied = _gate()
    if denied is not None:
        return denied
    return {
        "ok": True,
        "label": "cycle_recon main UI",
        "environment": os.getenv("REC_ENVIRONMENT") or "local",
        "runs_root": str(_runs_root()),
        "timezone_ui": "America/New_York",
        "trade_source_default": "postgres",
        "user_no": _session_slot(),
    }


@cycle_recon_router.get("/api/cycle_recon/trade_catalog")
def trade_catalog(
    range_preset: Optional[str] = Query(None, alias="range"),
    start_et: Optional[str] = None,
    end_et: Optional[str] = None,
    symbols: Optional[str] = Query(None, description="Comma-separated symbols"),
):
    """Symbols + tickers from the session tenant Postgres trade log for UI pickers."""
    denied = _gate()
    if denied is not None:
        return denied
    from backend.core.cycle_recon.trade_log_pg import trade_catalog_pg
    from backend.core.cycle_recon.time_util import to_et_display, to_iso_z

    try:
        min_d, max_d, start_u, end_u = _bounds_for_catalog(range_preset, start_et, end_et)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    sym_list = [s.strip() for s in (symbols or "").split(",") if s.strip()]
    try:
        cat = trade_catalog_pg(
            _session_slot(),
            min_date_et=min_d,
            max_date_et=max_d,
            symbols=sym_list or None,
        )
    except Exception as e:
        raise HTTPException(500, f"trade catalog failed: {e}") from e

    cat["range_preset"] = range_preset
    cat["bounds"] = {
        "start_utc": to_iso_z(start_u) if start_u else None,
        "end_utc": to_iso_z(end_u) if end_u else None,
        "start_et": to_et_display(start_u) if start_u else None,
        "end_et": to_et_display(end_u) if end_u else None,
        "min_date_et": min_d,
        "max_date_et": max_d,
    }
    return cat


@cycle_recon_router.get("/api/cycle_recon/runs")
def list_runs():
    denied = _gate()
    if denied is not None:
        return denied
    root = _runs_root()
    root.mkdir(parents=True, exist_ok=True)
    runs = []
    # In-progress partial dirs first
    for p in sorted(root.glob("*.partial"), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_dir():
            continue
        run_id = p.name[: -len(".partial")]
        prog = _partial_progress(run_id)
        runs.append(
            {
                "run_id": run_id,
                "path": str(p),
                "status": "running",
                "partial": True,
                "progress_bytes": prog.get("bytes"),
                "progress_files": prog.get("file_count"),
                "statuses": None,
                "market_count": None,
                "row_counts": None,
                "quality_markets": [],
                "handoff_archive": None,
            }
        )
    for p in sorted(root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_dir() or p.name.endswith(".partial"):
            continue
        summary: Dict[str, Any] = {}
        quality: Dict[str, Any] = {}
        sp = p / "summary.json"
        qp = p / "quality_report.json"
        if sp.is_file():
            try:
                summary = json.loads(sp.read_text(encoding="utf-8"))
            except Exception:
                pass
        if qp.is_file():
            try:
                quality = json.loads(qp.read_text(encoding="utf-8"))
            except Exception:
                pass
        runs.append(
            {
                "run_id": p.name,
                "path": str(p),
                "status": "complete",
                "partial": False,
                "statuses": summary.get("statuses"),
                "market_count": summary.get("market_count"),
                "row_counts": summary.get("row_counts"),
                "quality_markets": (quality.get("markets") or [])[:20],
                "handoff_archive": summary.get("handoff_archive"),
            }
        )
    return {"runs": runs}


@cycle_recon_router.get("/api/cycle_recon/jobs")
def list_jobs():
    denied = _gate()
    if denied is not None:
        return denied
    jobs: Dict[str, Dict[str, Any]] = {}
    with _LOCK:
        for jid, job in _JOBS.items():
            jobs[jid] = dict(job)
    # Disk metas (survive page refresh / process bookkeeping)
    for p in _jobs_dir().glob("*.json"):
        jid = p.stem
        if jid in jobs:
            continue
        meta = _read_job_meta(jid)
        if meta:
            jobs[jid] = meta
    # Partial dirs without meta
    for p in _runs_root().glob("ui_*.partial"):
        run_id = p.name[: -len(".partial")]
        jid = run_id[3:] if run_id.startswith("ui_") else run_id
        if jid in jobs:
            continue
        jobs[jid] = {
            "job_id": jid,
            "run_id": run_id,
            "status": "running",
            "started_at": p.stat().st_mtime,
            "source": "partial_dir",
        }
    enriched = [_enrich_job(j) for j in jobs.values()]
    enriched.sort(key=lambda x: float(x.get("started_at") or 0), reverse=True)
    # Only truly live processes count as active (dead+partial used to stick forever)
    active = [
        j
        for j in enriched
        if j.get("status") in ("running", "cancel_requested") and j.get("pid_alive")
    ]
    return {"jobs": enriched[:30], "active": active}


@cycle_recon_router.get("/api/cycle_recon/runs/{run_id}")
def get_run(run_id: str):
    denied = _gate()
    if denied is not None:
        return denied
    p = _runs_root() / run_id
    if not p.is_dir() or run_id.endswith(".partial"):
        raise HTTPException(404, "run not found")
    out: Dict[str, Any] = {
        "run_id": run_id,
        "path": str(p),
        "files": [x.name for x in p.iterdir() if x.is_file()],
        "handoff_archive": None,
    }
    for name in ("summary.json", "quality_report.json", "run_manifest.json", "analyst_index.json"):
        fp = p / name
        if fp.is_file():
            out[name] = json.loads(fp.read_text(encoding="utf-8"))
    summary = out.get("summary.json") or {}
    out["handoff_archive"] = summary.get("handoff_archive")
    siblings = []
    for suffix in (
        ".tar.zst",
        ".tar.gz",
        ".tar.zst.sha256",
        ".tar.gz.sha256",
        ".archive.partial",
        ".archive.failed",
    ):
        spath = _runs_root() / f"{run_id}{suffix}"
        if spath.is_file():
            siblings.append({"name": spath.name, "bytes": spath.stat().st_size})
    out["archive_siblings"] = siblings
    return out


@cycle_recon_router.get("/api/cycle_recon/runs/{run_id}/archive")
def download_archive(run_id: str):
    """Primary handoff download: canonical compressed archive next to the run dir."""
    denied = _gate()
    if denied is not None:
        return denied
    if "/" in run_id or "\\" in run_id or run_id.endswith(".partial"):
        raise HTTPException(400, "invalid run id")
    root = _runs_root()
    summary = {}
    sp = root / run_id / "summary.json"
    if sp.is_file():
        try:
            summary = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            pass
    arch = summary.get("handoff_archive") or {}
    candidates = []
    if arch.get("path"):
        candidates.append(Path(arch["path"]))
    if arch.get("filename"):
        candidates.append(root / arch["filename"])
    candidates.extend(
        [
            root / f"{run_id}.tar.zst",
            root / f"{run_id}.tar.gz",
        ]
    )
    for p in candidates:
        try:
            rp = p.resolve()
        except Exception:
            continue
        if not str(rp).startswith(str(root.resolve())):
            continue
        if rp.is_file():
            return FileResponse(rp, filename=rp.name)
    raise HTTPException(404, "handoff archive not found — run may predate packaging or archive failed")


@cycle_recon_router.get("/api/cycle_recon/runs/{run_id}/file/{name}")
def download_file(run_id: str, name: str):
    denied = _gate()
    if denied is not None:
        return denied
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "invalid file name")
    p = (_runs_root() / run_id / name).resolve()
    root = (_runs_root() / run_id).resolve()
    if not str(p).startswith(str(root)) or not p.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(p)


@cycle_recon_router.get("/api/cycle_recon/runs/{run_id}/preview")
def preview(run_id: str):
    denied = _gate()
    if denied is not None:
        return denied
    p = _runs_root() / run_id
    if not p.is_dir() or run_id.endswith(".partial"):
        raise HTTPException(404, "run not found")
    try:
        import pyarrow.parquet as pq
    except Exception as e:
        return {"error": f"pyarrow required for preview: {e}"}

    life_path = p / "trade_lifecycle.parquet"
    ladder_path = p / "whole_cent_ladder.parquet"
    preview_out: Dict[str, Any] = {"entry": None, "lifecycle_head": [], "ladder_entry": []}
    if life_path.is_file():
        life = pq.read_table(life_path).to_pylist()
        entries = [r for r in life if r.get("observation") == "entry"]
        preview_out["entry"] = entries[0] if entries else None
        preview_out["lifecycle_head"] = life[:40]
    if ladder_path.is_file():
        ladder = pq.read_table(ladder_path).to_pylist()
        preview_out["ladder_entry"] = [
            r
            for r in ladder
            if r.get("observation") == "entry" and r.get("ladder_kind") == "whole_cent_ask"
        ][:40]
    return preview_out


@cycle_recon_router.post("/api/cycle_recon/jobs")
def start_job(body: RunBody):
    denied = _gate()
    if denied is not None:
        return denied

    from backend.core.cycle_recon.time_util import to_iso_z
    from backend.core.cycle_recon.orchestrator import resolve_time_bounds, RunRequest

    slot = (body.user_no or "").strip() or _session_slot()
    use_pg = bool(body.use_pg) and not body.trade_log

    # Normalize Eastern UI → UTC for CLI --start/--end
    tmp = RunRequest(
        start=body.start,
        end=body.end,
        start_et=body.start_et,
        end_et=body.end_et,
        range_preset=body.range_preset,
    )
    try:
        start_u, end_u = resolve_time_bounds(tmp)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    job_id = uuid.uuid4().hex[:12]
    run_id = f"ui_{job_id}"
    py = _ROOT / ".venv" / "bin" / "python"
    if not py.is_file():
        py = Path(os.environ.get("PYTHON") or "python3")
    cmd = [
        str(py),
        str(_ROOT / "scripts" / "cycle_recon" / "reconstruct.py"),
        "--run-id",
        run_id,
        "--output-dir",
        str(_runs_root()),
        "--workers",
        str(max(1, min(int(body.workers or 1), 4))),
        "--user-no",
        slot,
    ]
    if body.range_preset:
        cmd += ["--range", body.range_preset]
    else:
        if body.start_et:
            cmd += ["--start-et", body.start_et]
        elif start_u:
            cmd += ["--start", to_iso_z(start_u)]
        if body.end_et:
            cmd += ["--end-et", body.end_et]
        elif end_u:
            cmd += ["--end", to_iso_z(end_u)]
    for s in body.symbols or []:
        cmd += ["--symbol", s]
    for t in body.tickers or []:
        cmd += ["--ticker", t]
    if body.trade_log:
        cmd += ["--trade-log", body.trade_log, "--no-pg"]
    elif not use_pg:
        cmd.append("--no-pg")
    for tid in body.trade_ids or []:
        cmd += ["--trade-id", tid]
    for m in body.monitors or []:
        cmd += ["--monitor", m]
    if body.force_refresh:
        cmd.append("--force-refresh")
    if body.offline:
        cmd.append("--offline")
    if body.export_csv:
        cmd.append("--export-csv")

    job_env = {
        **os.environ,
        "PYTHONPATH": str(_ROOT),
        "REC_USER_NO": slot,
        "REC_USER_SCHEMA": f"users_{slot}",
    }

    with _LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "run_id": run_id,
            "status": "running",
            "cmd": cmd,
            "started_at": time.time(),
            "returncode": None,
            "stdout_tail": "",
            "stderr_tail": "",
            "request": {
                "user_no": slot,
                "use_pg": use_pg,
                "range_preset": body.range_preset,
                "start_et": body.start_et,
                "end_et": body.end_et,
                "start_utc": to_iso_z(start_u) if start_u else None,
                "end_utc": to_iso_z(end_u) if end_u else None,
                "symbols": body.symbols,
                "tickers": body.tickers,
                "offline": body.offline,
            },
        }
        _write_job_meta(_JOBS[job_id])

    def _run() -> None:
        log_path = _job_log_path(job_id)
        log_f = open(log_path, "w", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(_ROOT),
                env=job_env,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            with _LOCK:
                _JOBS[job_id]["pid"] = proc.pid
                _write_job_meta(_JOBS[job_id])
            rc = proc.wait()
        finally:
            try:
                log_f.close()
            except Exception:
                pass
        log_tail = ""
        try:
            log_tail = _sanitize_text(log_path.read_text(encoding="utf-8", errors="replace"), limit=6000)
        except Exception:
            pass
        with _LOCK:
            cur = str(_JOBS[job_id].get("status") or "")
            if cur in ("cancel_requested", "cancelled"):
                _JOBS[job_id]["status"] = "cancelled"
            else:
                _JOBS[job_id]["status"] = "done" if rc == 0 else "error"
            _JOBS[job_id]["returncode"] = rc
            _JOBS[job_id]["stdout_tail"] = log_tail
            _JOBS[job_id]["stderr_tail"] = log_tail
            _JOBS[job_id]["finished_at"] = time.time()
            _write_job_meta(_JOBS[job_id])

    threading.Thread(target=_run, daemon=True).start()
    return {
        "job_id": job_id,
        "run_id": run_id,
        "status": "running",
        "user_no": slot,
        "started_at": time.time(),
    }


@cycle_recon_router.get("/api/cycle_recon/jobs/{job_id}")
def job_status(job_id: str):
    denied = _gate()
    if denied is not None:
        return denied
    job = _load_job(job_id)
    if not job:
        # Infer from partial/final run dir
        run_id = f"ui_{job_id}"
        prog = _partial_progress(run_id)
        if prog.get("partial") or prog.get("phase") == "complete_dir":
            job = {
                "job_id": job_id,
                "run_id": run_id,
                "status": "running" if prog.get("partial") else "done",
                "started_at": time.time(),
                "source": "inferred",
            }
        else:
            raise HTTPException(404, "job not found")
    return _enrich_job(job)


@cycle_recon_router.post("/api/cycle_recon/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    denied = _gate()
    if denied is not None:
        return denied
    jid = str(job_id).strip()
    job = _load_job(jid)
    if not job:
        # Orphan partial: job_id may be "manual_24h_btc" or full "ui_…"
        run_guess = jid if jid.startswith("ui_") else f"ui_{jid}"
        prog = _partial_progress(run_guess)
        if not prog.get("partial"):
            raise HTTPException(404, "job not found")
        job = {
            "job_id": jid[3:] if jid.startswith("ui_") else jid,
            "run_id": run_guess,
            "status": "running",
            "started_at": time.time(),
            "source": "partial_dir",
        }
        jid = str(job["job_id"])

    run_id = str(job.get("run_id") or f"ui_{jid}")
    pid = job.get("pid")
    with _LOCK:
        if jid in _JOBS:
            _JOBS[jid]["status"] = "cancel_requested"
            _write_job_meta(_JOBS[jid])
        else:
            job["status"] = "cancel_requested"
            _write_job_meta(job)

    kill_info = _kill_job_process(pid if pid else None)
    try:
        for line in subprocess.check_output(["ps", "aux"], text=True).splitlines():
            if "reconstruct.py" in line and run_id in line:
                try:
                    kill_info = _kill_job_process(int(line.split()[1]))
                except Exception:
                    pass
    except Exception:
        pass

    abandoned = _abandon_partial(run_id)
    finished = _mark_job_finished(
        {**job, "job_id": jid, "run_id": run_id, "pid": pid},
        "cancelled",
        note="cancelled by operator"
        + (f"; abandoned={abandoned}" if abandoned else "")
        + f"; kill={kill_info}",
    )
    return {
        "ok": True,
        "status": "cancelled",
        "job": _enrich_job(finished),
        "kill": kill_info,
        "abandoned_partial": abandoned,
    }
