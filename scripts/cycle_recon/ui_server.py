#!/usr/bin/env python3
"""
Localhost-only prototype UI for cycle reconstruction.

Bind: 127.0.0.1:8765 (override with CYCLE_RECON_UI_PORT)

  PYTHONPATH=. .venv/bin/python scripts/cycle_recon/ui_server.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
import uvicorn

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core.cycle_recon.package_writer import default_runs_root

app = FastAPI(title="Cycle Recon (local analysis only)")
_JOBS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


class RunBody(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    tickers: list[str] = Field(default_factory=list)
    trade_log: Optional[str] = None
    trade_ids: list[str] = Field(default_factory=list)
    monitors: list[str] = Field(default_factory=list)
    workers: int = 2
    force_refresh: bool = False
    offline: bool = False
    export_csv: bool = False


def _runs_root() -> Path:
    return default_runs_root()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "bind": "127.0.0.1", "label": "local analysis tooling"}


@app.get("/api/runs")
def list_runs() -> dict:
    root = _runs_root()
    root.mkdir(parents=True, exist_ok=True)
    runs = []
    for p in sorted(root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_dir() or p.name.endswith(".partial"):
            continue
        summary = {}
        quality = {}
        sp = p / "summary.json"
        qp = p / "quality_report.json"
        if sp.is_file():
            try:
                summary = json.loads(sp.read_text())
            except Exception:
                pass
        if qp.is_file():
            try:
                quality = json.loads(qp.read_text())
            except Exception:
                pass
        runs.append(
            {
                "run_id": p.name,
                "path": str(p),
                "statuses": summary.get("statuses"),
                "market_count": summary.get("market_count"),
                "row_counts": summary.get("row_counts"),
                "quality_markets": (quality.get("markets") or [])[:20],
                "handoff_archive": summary.get("handoff_archive"),
            }
        )
    return {"runs": runs}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    p = _runs_root() / run_id
    if not p.is_dir():
        raise HTTPException(404, "run not found")
    out = {"run_id": run_id, "path": str(p), "files": [x.name for x in p.iterdir() if x.is_file()]}
    for name in ("summary.json", "quality_report.json", "run_manifest.json"):
        fp = p / name
        if fp.is_file():
            out[name] = json.loads(fp.read_text())
    return out


@app.get("/api/runs/{run_id}/file/{name}")
def download_file(run_id: str, name: str):
    p = (_runs_root() / run_id / name).resolve()
    root = (_runs_root() / run_id).resolve()
    if not str(p).startswith(str(root)) or not p.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(p)


@app.get("/api/runs/{run_id}/archive")
def download_archive(run_id: str):
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
        candidates.append(root / str(arch["filename"]))
    candidates.extend([root / f"{run_id}.tar.zst", root / f"{run_id}.tar.gz"])
    for p in candidates:
        try:
            rp = p.resolve()
        except Exception:
            continue
        if str(rp).startswith(str(root.resolve())) and rp.is_file():
            return FileResponse(rp, filename=rp.name)
    raise HTTPException(404, "handoff archive not found")


@app.get("/api/runs/{run_id}/preview")
def preview(run_id: str) -> dict:
    """Compact entry snapshot + lifecycle preview for first trade."""
    p = _runs_root() / run_id
    if not p.is_dir():
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
            r for r in ladder if r.get("observation") == "entry" and r.get("ladder_kind") == "whole_cent_ask"
        ][:40]
    return preview_out


def _sanitize_text(s: str, *, limit: int = 4000) -> str:
    """Strip control chars so job status JSON stays valid for browsers/clients."""
    if not s:
        return ""
    cleaned = "".join(ch if (ch == "\n" or ch == "\t" or ord(ch) >= 32) else "?" for ch in s)
    return cleaned[-limit:]


@app.post("/api/jobs")
def start_job(body: RunBody) -> dict:
    job_id = uuid.uuid4().hex[:12]
    run_id = f"ui_{job_id}"
    cmd = [
        str(_ROOT / ".venv" / "bin" / "python"),
        str(_ROOT / "scripts" / "cycle_recon" / "reconstruct.py"),
        "--run-id",
        run_id,
        "--output-dir",
        str(_runs_root()),
        "--workers",
        str(max(1, min(body.workers, 4))),
    ]
    if body.start:
        cmd += ["--start", body.start]
    if body.end:
        cmd += ["--end", body.end]
    for t in body.tickers:
        cmd += ["--ticker", t]
    if body.trade_log:
        cmd += ["--trade-log", body.trade_log]
    for tid in body.trade_ids:
        cmd += ["--trade-id", tid]
    for m in body.monitors:
        cmd += ["--monitor", m]
    if body.force_refresh:
        cmd.append("--force-refresh")
    if body.offline:
        cmd.append("--offline")
    if body.export_csv:
        cmd.append("--export-csv")

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
        }

    def _run() -> None:
        proc = subprocess.Popen(
            cmd,
            cwd=str(_ROOT),
            env={**os.environ, "PYTHONPATH": str(_ROOT)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        with _LOCK:
            _JOBS[job_id]["pid"] = proc.pid
        out, err = proc.communicate()
        with _LOCK:
            _JOBS[job_id]["status"] = "done" if proc.returncode == 0 else "error"
            _JOBS[job_id]["returncode"] = proc.returncode
            _JOBS[job_id]["stdout_tail"] = _sanitize_text(out or "")
            _JOBS[job_id]["stderr_tail"] = _sanitize_text(err or "")
            _JOBS[job_id]["finished_at"] = time.time()

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "run_id": run_id, "status": "running"}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        # Return a copy with sanitized tails (in case older jobs predate sanitizer)
        out = dict(job)
        out["stdout_tail"] = _sanitize_text(str(out.get("stdout_tail") or ""))
        out["stderr_tail"] = _sanitize_text(str(out.get("stderr_tail") or ""))
        return out


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        pid = job.get("pid")
        job["status"] = "cancel_requested"
    if pid:
        try:
            os.kill(pid, 15)
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": True}


INDEX_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Cycle Recon — local analysis</title>
  <style>
    body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 24px; max-width: 1100px; }
    .banner { background: #fff3cd; border: 1px solid #ffeeba; padding: 10px 12px; margin-bottom: 16px; }
    label { display:block; margin-top: 8px; font-size: 13px; }
    input, textarea { width: 100%; padding: 6px; box-sizing: border-box; }
    .row { display:grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    button { margin-top: 12px; padding: 8px 14px; }
    pre { background: #f6f8fa; padding: 10px; overflow:auto; font-size: 12px; }
    table { border-collapse: collapse; width: 100%; font-size: 13px; }
    td, th { border-bottom: 1px solid #ddd; padding: 6px; text-align: left; }
  </style>
</head>
<body>
  <div class="banner"><b>Local analysis tooling</b> — binds to 127.0.0.1 only. Does not mutate production.</div>
  <h1>Cycle reconstruction</h1>
  <div class="row">
    <div>
      <label>Start (UTC ISO)</label><input id="start"/>
      <label>End (UTC ISO)</label><input id="end"/>
      <label>Tickers (comma-separated)</label><input id="tickers"/>
    </div>
    <div>
      <label>Trade log CSV path</label><input id="trade_log" value="tests/fixtures/cycle_recon/10058_full_09_05.csv"/>
      <label>Trade IDs (comma-separated)</label><input id="trade_ids" value="55286,55388"/>
      <label>Workers</label><input id="workers" value="2"/>
    </div>
  </div>
  <button onclick="startJob()">Start local run</button>
  <button onclick="refreshRuns()">Refresh packages</button>
  <h2>Job</h2>
  <pre id="job">none</pre>
  <h2>Packages</h2>
  <div id="runs"></div>
  <h2>Preview</h2>
  <pre id="preview">select a run</pre>
<script>
let currentJob=null;
async function startJob(){
  const body={
    start: document.getElementById('start').value||null,
    end: document.getElementById('end').value||null,
    tickers: document.getElementById('tickers').value.split(',').map(s=>s.trim()).filter(Boolean),
    trade_log: document.getElementById('trade_log').value||null,
    trade_ids: document.getElementById('trade_ids').value.split(',').map(s=>s.trim()).filter(Boolean),
    workers: parseInt(document.getElementById('workers').value||'2',10)
  };
  const r=await fetch('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  currentJob=await r.json();
  document.getElementById('job').textContent=JSON.stringify(currentJob,null,2);
  pollJob();
}
async function pollJob(){
  if(!currentJob) return;
  const r=await fetch('/api/jobs/'+currentJob.job_id);
  const j=await r.json();
  document.getElementById('job').textContent=JSON.stringify(j,null,2);
  if(j.status==='running'||j.status==='cancel_requested'){ setTimeout(pollJob,2000); }
  else { refreshRuns(); }
}
async function refreshRuns(){
  const r=await fetch('/api/runs');
  const data=await r.json();
  const el=document.getElementById('runs');
  el.innerHTML='<table><tr><th>run</th><th>markets</th><th>statuses</th><th>handoff</th><th>files</th></tr>'+
    (data.runs||[]).map(x=>{
      const arch=x.handoff_archive||{};
      const handoff=arch.filename||arch.path
        ? `<a href="/api/runs/${x.run_id}/archive"><b>Download archive</b></a>`
        : (arch.error?'archive failed':'no archive');
      return `<tr>
      <td>${x.run_id}</td><td>${x.market_count||''}</td><td>${JSON.stringify(x.statuses||{})}</td>
      <td>${handoff}</td>
      <td><button onclick="preview('${x.run_id}')">preview</button>
      <a href="/api/runs/${x.run_id}/file/summary.json" target="_blank">summary</a>
      <a href="/api/runs/${x.run_id}/file/quality_report.json" target="_blank">quality</a>
      <a href="/api/runs/${x.run_id}/file/analyst_index.json" target="_blank">index</a></td>
    </tr>`;
    }).join('')+'</table>';
}
async function preview(runId){
  const r=await fetch('/api/runs/'+runId+'/preview');
  document.getElementById('preview').textContent=JSON.stringify(await r.json(),null,2);
}
refreshRuns();
</script>
</body>
</html>
"""


def main() -> None:
    port = int(os.environ.get("CYCLE_RECON_UI_PORT") or "8765")
    print(f"Cycle recon UI (local analysis only) http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
