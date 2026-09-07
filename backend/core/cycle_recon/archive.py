"""
Canonical compressed handoff archive for cycle reconstruction packages.

Preferred: ``<run_id>.tar.zst`` (python-zstandard or system ``zstd``).
Fallback: ``<run_id>.tar.gz``.

Atomic publish: write ``*.archive.partial``, verify list/extract + checksums,
then rename to the final archive name. Never leaves a final name on failure.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.core.cycle_recon.hashing import sha256_file
from backend.core.cycle_recon.version import GENERATOR_VERSION, SCHEMA_VERSION

# Fixed mtime for deterministic tar members (Unix epoch seconds).
_DETERMINISTIC_MTIME = 1_700_000_000

_REQUIRED_JSON = (
    "README.md",
    "schema.json",
    "run_manifest.json",
    "summary.json",
    "quality_report.json",
)

_TABLE_DESCRIPTIONS: Dict[str, str] = {
    "markets": "Per-market quality status, archive hashes, public-trade meta",
    "strategy_trades": "Source-scoped strategy trade rows used for this run",
    "book_events": "Every snapshot/delta event applied during reconstruction",
    "initial_book_snapshots": "Full ladder levels from each snapshot era",
    "book_timeseries": "1s regularized book samples + rolling activity",
    "whole_cent_ladder": "Whole-cent ask ladder rows at key observations",
    "public_trades": "Cached Kalshi public tape for included markets",
    "symbol_timeseries": "BTC/symbol price ring from the sealed package",
    "trade_lifecycle": "As-of lifecycle observations (entry/pre-entry/close)",
}

_EXCLUDE_NAMES = {".incomplete", ".DS_Store"}


@dataclass
class ArchiveResult:
    run_id: str
    archive_path: str
    format: str  # tar.zst | tar.gz
    compressor: str  # python-zstandard | cli-zstd | gzip
    bytes: int
    sha256: str
    compression_s: float
    member_count: int
    source_dir_bytes: int
    checksums_path: str
    analyst_index_path: str
    verified: bool = True
    error: Optional[str] = None


def zstd_capability() -> Tuple[bool, str]:
    """Return (available, how) for zstd compression."""
    try:
        import zstandard  # noqa: F401

        return True, "python-zstandard"
    except Exception:
        pass
    if shutil.which("zstd"):
        return True, "cli-zstd"
    return False, "unavailable"


def select_archive_format() -> Tuple[str, str]:
    """Prefer tar.zst when any zstd compressor is available; else tar.gz."""
    ok, how = zstd_capability()
    if ok:
        return "tar.zst", how
    return "tar.gz", "gzip"


def _is_excluded(rel: str) -> bool:
    name = Path(rel).name
    if name in _EXCLUDE_NAMES or name.startswith("."):
        return True
    norm = rel.replace("\\", "/")
    if norm == "debug" or norm.startswith("debug/"):
        return True
    return False


def list_package_files(run_dir: Path) -> List[str]:
    """Sorted relative paths of files to include in the handoff archive."""
    run_dir = Path(run_dir)
    out: List[str] = []
    for root, dirs, files in os.walk(run_dir):
        dirs[:] = [
            d
            for d in dirs
            if d not in _EXCLUDE_NAMES and not d.startswith(".") and d != "debug"
        ]
        for fn in files:
            full = Path(root) / fn
            rel = full.relative_to(run_dir).as_posix()
            if _is_excluded(rel):
                continue
            out.append(rel)
    out.sort()
    return out


def write_checksums_file(
    run_dir: Path, *, exclude: Sequence[str] = ("checksums.sha256",)
) -> Path:
    """Write checksums.sha256 for all package files (sorted). Returns path."""
    run_dir = Path(run_dir)
    skip = set(exclude)
    lines: List[str] = []
    for rel in list_package_files(run_dir):
        if rel in skip:
            continue
        digest = sha256_file(run_dir / rel)
        lines.append(f"{digest}  {rel}")
    path = run_dir / "checksums.sha256"
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_analyst_index(run_dir: Path, *, run_id: Optional[str] = None) -> Dict[str, Any]:
    run_dir = Path(run_dir)
    rid = run_id or run_dir.name
    summary = _load_json(run_dir / "summary.json")
    quality = _load_json(run_dir / "quality_report.json")
    manifest = _load_json(run_dir / "run_manifest.json")
    request = manifest.get("request") or {}

    tickers: List[str] = []
    utc_start = request.get("start")
    utc_end = request.get("end")
    trade_ids = list(request.get("trade_ids") or [])
    source_hashes: Dict[str, Any] = {}

    markets_path = run_dir / "markets.parquet"
    if markets_path.is_file():
        try:
            import pyarrow.parquet as pq

            rows = pq.read_table(markets_path).to_pylist()
            for r in rows:
                t = r.get("ticker")
                if t:
                    tickers.append(str(t))
                if r.get("archive_sha256"):
                    source_hashes[f"archive:{t}"] = r.get("archive_sha256")
                pm = r.get("public_trades_meta")
                if isinstance(pm, str):
                    try:
                        pm = json.loads(pm)
                    except Exception:
                        pm = {}
                if isinstance(pm, dict) and pm.get("sha256"):
                    source_hashes[f"public_trades:{t}"] = pm.get("sha256")
                open_u = r.get("cycle_open_utc")
                close_u = r.get("cycle_close_utc")
                if open_u and (utc_start is None or str(open_u) < str(utc_start)):
                    utc_start = open_u
                if close_u and (utc_end is None or str(close_u) > str(utc_end)):
                    utc_end = close_u
        except Exception:
            pass

    if not tickers:
        tickers = list(request.get("tickers") or [])

    trade_identities: List[str] = []
    strat_path = run_dir / "strategy_trades.parquet"
    if strat_path.is_file():
        try:
            import pyarrow.parquet as pq

            for r in pq.read_table(strat_path).to_pylist():
                if r.get("trade_identity"):
                    trade_identities.append(str(r["trade_identity"]))
                tid = r.get("trade_id")
                if tid and str(tid) not in trade_ids:
                    trade_ids.append(str(tid))
                if r.get("source_sha256"):
                    source_hashes["trade_log"] = r.get("source_sha256")
        except Exception:
            pass

    q_markets = quality.get("markets") or []
    quality_states = {
        str(m.get("ticker") or "?"): m.get("status") for m in q_markets if isinstance(m, dict)
    }

    row_counts = summary.get("row_counts") or {}
    tables: Dict[str, Any] = {}
    for name, desc in _TABLE_DESCRIPTIONS.items():
        p = run_dir / f"{name}.parquet"
        alt = None
        if not p.is_file():
            for cand in run_dir.glob(f"{name}.*"):
                if cand.suffix in (".parquet", ".jsonl") or cand.name.endswith(".jsonl.zst"):
                    alt = cand
                    break
        tables[name] = {
            "description": desc,
            "rows": row_counts.get(name),
            "present": p.is_file() or alt is not None,
            "path": (p.name if p.is_file() else (alt.name if alt else None)),
        }

    et_start = None
    et_end = None
    try:
        from backend.core.cycle_recon.time_util import parse_utc, to_et_display

        if utc_start:
            et_start = to_et_display(parse_utc(str(utc_start)))
        if utc_end:
            et_end = to_et_display(parse_utc(str(utc_end)))
    except Exception:
        pass

    return {
        "package_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "run_id": rid,
        "created_at_utc": manifest.get("created_at_utc")
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "time_range": {
            "utc_start": utc_start,
            "utc_end": utc_end,
            "et_start": et_start,
            "et_end": et_end,
        },
        "tickers": tickers,
        "trade_ids": trade_ids,
        "trade_identities": trade_identities,
        "row_counts": row_counts,
        "tables": tables,
        "quality_state": {
            "statuses": summary.get("statuses"),
            "per_market": quality_states,
        },
        "source_hashes": source_hashes,
        "known_missing_data_limitations": summary.get("unavailable_by_design")
        or [
            "exchange-level BTC trades",
            "order IDs / queue position",
            "cancellation identity",
            "reliable aggressor when tape lacks taker fields (emitted as UNKNOWN)",
            "missing trigger timestamps not present in trade log",
        ],
        "what_you_can_answer": summary.get("what_you_can_answer") or [],
        "git_revision": manifest.get("git_revision"),
        "request": {
            "start": request.get("start"),
            "end": request.get("end"),
            "tickers": request.get("tickers"),
            "trade_log": request.get("trade_log"),
            "trade_ids": request.get("trade_ids"),
            "offline": request.get("offline"),
        },
    }


def write_analyst_index(run_dir: Path) -> Path:
    run_dir = Path(run_dir)
    idx = build_analyst_index(run_dir)
    path = run_dir / "analyst_index.json"
    path.write_text(json.dumps(idx, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def _dir_byte_size(run_dir: Path, files: Sequence[str]) -> int:
    total = 0
    for rel in files:
        total += (run_dir / rel).stat().st_size
    return total


def _build_tar_bytes(run_dir: Path, run_id: str, files: Sequence[str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for rel in files:
            full = run_dir / rel
            data = full.read_bytes()
            info = tarfile.TarInfo(name=f"{run_id}/{rel}")
            info.size = len(data)
            info.mtime = _DETERMINISTIC_MTIME
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _compress_zstd_python(raw: bytes) -> bytes:
    import zstandard

    cctx = zstandard.ZstdCompressor(level=3)
    return cctx.compress(raw)


def _compress_zstd_cli(raw: bytes) -> bytes:
    proc = subprocess.run(
        ["zstd", "-q", "-3", "-c", "-"],
        input=raw,
        capture_output=True,
        check=True,
    )
    return proc.stdout


def _compress_gzip(raw: bytes) -> bytes:
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", compresslevel=6, mtime=0) as gz:
        gz.write(raw)
    return out.getvalue()


def _compress(raw: bytes, fmt: str, compressor: str) -> bytes:
    if fmt == "tar.zst":
        if compressor == "python-zstandard":
            return _compress_zstd_python(raw)
        if compressor == "cli-zstd":
            return _compress_zstd_cli(raw)
        raise RuntimeError(f"zstd requested but compressor unavailable: {compressor}")
    if fmt == "tar.gz":
        return _compress_gzip(raw)
    raise RuntimeError(f"unknown archive format: {fmt}")


def _extract_archive(archive_path: Path, dest: Path, *, fmt: str) -> None:
    blob = archive_path.read_bytes()
    if fmt == "tar.zst":
        try:
            import zstandard

            raw = zstandard.ZstdDecompressor().decompress(blob)
        except Exception:
            proc = subprocess.run(
                ["zstd", "-q", "-d", "-c", str(archive_path)],
                capture_output=True,
                check=True,
            )
            raw = proc.stdout
    elif fmt == "tar.gz":
        raw = gzip.decompress(blob)
    else:
        raise RuntimeError(f"unknown format {fmt}")
    bio = io.BytesIO(raw)
    with tarfile.open(fileobj=bio, mode="r:") as tar:
        tar.extractall(dest)


def _verify_archive(
    archive_path: Path,
    *,
    fmt: str,
    expected_files: Sequence[str],
    run_id: str,
    run_dir: Path,
) -> None:
    """List/extract archive into a temp dir and verify checksums.sha256 entries."""
    with tempfile.TemporaryDirectory(prefix="cycle_recon_arch_verify_") as tmp:
        tmp_path = Path(tmp)
        _extract_archive(archive_path, tmp_path, fmt=fmt)
        root = tmp_path / run_id
        if not root.is_dir():
            raise RuntimeError(f"archive missing top-level directory {run_id}/")
        members = sorted(
            p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
        )
        expected = sorted(expected_files)
        if members != expected:
            missing = sorted(set(expected) - set(members))
            extra = sorted(set(members) - set(expected))
            raise RuntimeError(
                f"archive member mismatch missing={missing[:10]} extra={extra[:10]}"
            )

        chk = root / "checksums.sha256"
        if not chk.is_file():
            raise RuntimeError("archive missing checksums.sha256")
        for line in chk.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                raise RuntimeError(f"bad checksums line: {line!r}")
            digest, rel = parts[0], parts[1].lstrip("*").strip()
            got = sha256_file(root / rel)
            if got != digest:
                raise RuntimeError(f"checksum mismatch for {rel}: {got} != {digest}")
            src = run_dir / rel
            if src.is_file() and sha256_file(src) != digest:
                raise RuntimeError(f"source drifted from archive for {rel}")


def prepare_package_for_archive(run_dir: Path) -> Tuple[Path, Path, List[str]]:
    """Write analyst_index.json + checksums.sha256 into run_dir."""
    run_dir = Path(run_dir)
    idx = write_analyst_index(run_dir)
    chk = write_checksums_file(run_dir, exclude=("checksums.sha256",))
    files = list_package_files(run_dir)
    return idx, chk, files


def create_handoff_archive(
    run_dir: Path,
    *,
    output_dir: Optional[Path] = None,
    force_format: Optional[str] = None,
) -> ArchiveResult:
    """
    Create canonical handoff archive next to the run directory.

    On failure, leaves ``<run_id>.archive.partial`` and/or ``.archive.failed``
    and never publishes the final archive name.
    """
    run_dir = Path(run_dir).resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run directory not found: {run_dir}")
    run_id = run_dir.name
    out_root = Path(output_dir).resolve() if output_dir else run_dir.parent

    fmt, compressor = select_archive_format()
    if force_format:
        if force_format not in ("tar.zst", "tar.gz"):
            raise ValueError("force_format must be tar.zst or tar.gz")
        fmt = force_format
        if fmt == "tar.zst":
            ok, how = zstd_capability()
            if not ok:
                raise RuntimeError("tar.zst requested but zstd unavailable")
            compressor = how
        else:
            compressor = "gzip"

    final_name = f"{run_id}.{fmt}"
    final_path = out_root / final_name
    partial_path = out_root / f"{run_id}.archive.partial"
    failed_marker = out_root / f"{run_id}.archive.failed"

    if failed_marker.exists():
        failed_marker.unlink()
    if partial_path.exists():
        if partial_path.is_dir():
            shutil.rmtree(partial_path)
        else:
            partial_path.unlink()

    t0 = time.perf_counter()
    try:
        idx_path, chk_path, files = prepare_package_for_archive(run_dir)
        files = list_package_files(run_dir)

        src_bytes = _dir_byte_size(run_dir, files)
        tar_bytes = _build_tar_bytes(run_dir, run_id, files)
        compressed = _compress(tar_bytes, fmt, compressor)
        partial_path.write_bytes(compressed)

        _verify_archive(
            partial_path,
            fmt=fmt,
            expected_files=files,
            run_id=run_id,
            run_dir=run_dir,
        )

        digest = sha256_file(partial_path)
        if final_path.exists():
            final_path.unlink()
        partial_path.rename(final_path)

        (out_root / f"{final_name}.sha256").write_text(
            f"{digest}  {final_name}\n", encoding="utf-8"
        )

        compression_s = time.perf_counter() - t0
        return ArchiveResult(
            run_id=run_id,
            archive_path=str(final_path),
            format=fmt,
            compressor=compressor,
            bytes=final_path.stat().st_size,
            sha256=digest,
            compression_s=compression_s,
            member_count=len(files),
            source_dir_bytes=src_bytes,
            checksums_path=str(chk_path),
            analyst_index_path=str(idx_path),
            verified=True,
        )
    except Exception as e:
        if final_path.exists():
            try:
                final_path.unlink()
            except Exception:
                pass
        failed_marker.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "error": str(e),
                    "partial_path": str(partial_path) if partial_path.exists() else None,
                    "at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        raise


def archive_result_dict(result: ArchiveResult) -> Dict[str, Any]:
    return {
        "path": result.archive_path,
        "filename": Path(result.archive_path).name,
        "format": result.format,
        "compressor": result.compressor,
        "bytes": result.bytes,
        "sha256": result.sha256,
        "compression_s": round(result.compression_s, 4),
        "member_count": result.member_count,
        "source_dir_bytes": result.source_dir_bytes,
        "compression_ratio": (
            round(result.source_dir_bytes / result.bytes, 4) if result.bytes else None
        ),
        "verified": result.verified,
    }


def patch_summary_with_archive(run_dir: Path, result: ArchiveResult) -> None:
    """Update on-disk summary.json + run_manifest.json with archive metadata."""
    run_dir = Path(run_dir)
    archive_block = archive_result_dict(result)
    for name in ("summary.json", "run_manifest.json"):
        path = run_dir / name
        if not path.is_file():
            continue
        obj = _load_json(path)
        obj["handoff_archive"] = archive_block
        path.write_text(json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8")
