from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.cycle_recon.version import GENERATOR_VERSION, SCHEMA_VERSION

TABLE_NAMES = (
    "markets",
    "strategy_trades",
    "book_events",
    "initial_book_snapshots",
    "book_timeseries",
    "whole_cent_ladder",
    "public_trades",
    "symbol_timeseries",
    "trade_lifecycle",
)


def pyarrow_available() -> bool:
    try:
        import pyarrow  # noqa: F401
        import pyarrow.parquet  # noqa: F401

        return True
    except Exception:
        return False


def _git_revision() -> Optional[str]:
    try:
        import subprocess

        root = Path(__file__).resolve().parents[3]
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(root), stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except Exception:
        return None


def default_runs_root() -> Path:
    env = (os.environ.get("CYCLE_RECON_RUNS") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (
        Path(__file__).resolve().parents[2]
        / "data"
        / "historical_data"
        / "cycle_recon_runs"
    )


def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, (dict, list, tuple)):
            out[k] = json.dumps(v, separators=(",", ":"), default=str)
        elif isinstance(v, datetime):
            out[k] = v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        elif isinstance(v, bool) or v is None:
            out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = v
        else:
            # bytes / Decimal / stray objects → stable string
            out[k] = str(v)
    return out


def _unify_batch_columns(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Make each column Arrow-friendly within a batch.
    Mixed str/float (common in API tape) becomes all strings.
    """
    if not rows:
        return rows
    keys: List[str] = []
    seen = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)
    unified = [{k: r.get(k) for k in keys} for r in rows]
    for k in keys:
        kinds = set()
        for r in unified:
            v = r.get(k)
            if v is None:
                continue
            if isinstance(v, bool):
                kinds.add("bool")
            elif isinstance(v, int):
                kinds.add("int")
            elif isinstance(v, float):
                kinds.add("float")
            elif isinstance(v, str):
                kinds.add("str")
            else:
                kinds.add("other")
        if not kinds or kinds <= {"int"} or kinds <= {"float"} or kinds <= {"bool"} or kinds <= {"str"}:
            continue
        if kinds <= {"int", "float"}:
            for r in unified:
                if r.get(k) is not None:
                    r[k] = float(r[k])
            continue
        for r in unified:
            if r.get(k) is not None:
                r[k] = str(r[k])
    return unified


class StreamingParquetTable:
    """Append-only parquet writer; releases row batches after each flush."""

    def __init__(self, path: Path, *, batch_size: int = 20000):
        self.path = Path(path)
        self.batch_size = batch_size
        self._buf: List[Dict[str, Any]] = []
        self._writer = None
        self._schema = None
        self.rows = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, row: Dict[str, Any]) -> None:
        self._buf.append(_normalize_row(row))
        if len(self._buf) >= self.batch_size:
            self.flush()

    def extend(self, rows: List[Dict[str, Any]]) -> None:
        for r in rows:
            self.append(r)

    def flush(self) -> None:
        if not self._buf:
            return
        if not pyarrow_available():
            # Fallback: append JSONL
            out = self.path.with_suffix(".jsonl")
            with out.open("a", encoding="utf-8") as f:
                for r in self._buf:
                    f.write(json.dumps(r, separators=(",", ":"), default=str) + "\n")
            self.rows += len(self._buf)
            self._buf.clear()
            return

        import pyarrow as pa
        import pyarrow.parquet as pq

        batch = _unify_batch_columns(self._buf)
        table = pa.Table.from_pylist(batch)
        if self._writer is None:
            self._schema = table.schema
            self._writer = pq.ParquetWriter(self.path, self._schema, compression="zstd")
        else:
            # Align columns to writer schema (add missing nulls)
            table = _align_table(table, self._schema)
        self._writer.write_table(table)
        self.rows += len(self._buf)
        self._buf.clear()
        del table
        del batch

    def close(self) -> Dict[str, Any]:
        self.flush()
        if self._writer is not None:
            self._writer.close()
            self._writer = None
            return {"path": self.path.name, "encoding": "parquet", "rows": self.rows}
        # jsonl fallback path
        out = self.path.with_suffix(".jsonl")
        if out.exists():
            return {"path": out.name, "encoding": "jsonl", "rows": self.rows}
        # empty table
        if pyarrow_available():
            import pyarrow as pa
            import pyarrow.parquet as pq

            pq.write_table(pa.table({"_empty": []}), self.path)
            return {"path": self.path.name, "encoding": "parquet", "rows": 0}
        out.write_text("", encoding="utf-8")
        return {"path": out.name, "encoding": "jsonl", "rows": 0}


def _align_table(table: Any, schema: Any) -> Any:
    import pyarrow as pa

    cols = []
    for field in schema:
        if field.name in table.column_names:
            col = table.column(field.name)
            try:
                col = col.cast(field.type, safe=False)
            except Exception:
                # stringify as last resort
                col = pa.array([None if v is None else str(v) for v in col.to_pylist()], type=field.type)
            cols.append(col)
        else:
            cols.append(pa.nulls(table.num_rows, type=field.type))
    return pa.Table.from_arrays(cols, schema=schema)


def write_table(
    path_stem: Path,
    rows: List[Dict[str, Any]],
    *,
    prefer_parquet: bool = True,
) -> Dict[str, Any]:
    path_stem.parent.mkdir(parents=True, exist_ok=True)
    if prefer_parquet and pyarrow_available():
        w = StreamingParquetTable(path_stem.with_suffix(".parquet"), batch_size=20000)
        w.extend(rows)
        return w.close()
    payload_lines = [json.dumps(_normalize_row(r), separators=(",", ":"), default=str) for r in rows]
    body = ("\n".join(payload_lines) + ("\n" if payload_lines else "")).encode("utf-8")
    try:
        import zstandard as zstd  # type: ignore

        out = path_stem.with_suffix(".jsonl.zst")
        out.write_bytes(zstd.ZstdCompressor(level=3).compress(body))
        return {"path": str(out.name), "encoding": "jsonl.zst", "rows": len(rows)}
    except Exception:
        out = path_stem.with_suffix(".jsonl")
        out.write_bytes(body)
        return {
            "path": str(out.name),
            "encoding": "jsonl",
            "rows": len(rows),
            "warning": "pyarrow_unavailable_and_zstandard_unavailable",
        }


def write_csv_debug(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: List[str] = []
    seen = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(_normalize_row(r))


class PackageBuilder:
    def __init__(self, output_dir: Path, run_id: str):
        self.output_dir = Path(output_dir)
        self.run_id = run_id
        self.partial = self.output_dir / f"{run_id}.partial"
        self.final = self.output_dir / run_id
        if self.partial.exists():
            import shutil

            shutil.rmtree(self.partial)
        self.partial.mkdir(parents=True, exist_ok=True)
        (self.partial / ".incomplete").write_text("1", encoding="utf-8")
        self.file_inventory: Dict[str, Any] = {}
        self.encoding = "parquet" if pyarrow_available() else "jsonl.zst_or_jsonl"
        self._streams: Dict[str, StreamingParquetTable] = {}

    def stream(self, name: str) -> StreamingParquetTable:
        if name not in self._streams:
            self._streams[name] = StreamingParquetTable(self.partial / f"{name}.parquet")
        return self._streams[name]

    def write_table(self, name: str, rows: List[Dict[str, Any]], *, export_csv: bool = False) -> None:
        if name in self._streams:
            self._streams[name].extend(rows)
        else:
            meta = write_table(self.partial / name, rows, prefer_parquet=True)
            self.file_inventory[name] = meta
        if export_csv and rows:
            write_csv_debug(self.partial / "debug" / f"{name}.csv", rows)

    def write_json(self, name: str, obj: Dict[str, Any]) -> None:
        path = self.partial / name
        path.write_text(json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8")
        self.file_inventory[name] = {"path": name, "encoding": "json"}

    def write_text(self, name: str, text: str) -> None:
        (self.partial / name).write_text(text, encoding="utf-8")
        self.file_inventory[name] = {"path": name, "encoding": "text"}

    def close_streams(self) -> None:
        for name, stream in list(self._streams.items()):
            self.file_inventory[name] = stream.close()
        self._streams.clear()

    def finalize(
        self,
        *,
        request: Dict[str, Any],
        quality_report: Dict[str, Any],
        summary: Dict[str, Any],
        readme: str,
        status: str = "complete",
    ) -> Path:
        self.close_streams()
        manifest = {
            "run_id": self.run_id,
            "status": status,
            "schema_version": SCHEMA_VERSION,
            "generator_version": GENERATOR_VERSION,
            "git_revision": _git_revision(),
            "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "request": request,
            "table_encoding": self.encoding,
            "file_inventory": self.file_inventory,
            "pyarrow_available": pyarrow_available(),
        }
        self.write_json("run_manifest.json", manifest)
        self.write_json("quality_report.json", quality_report)
        summary = dict(summary)
        summary["file_inventory"] = self.file_inventory
        self.write_json("summary.json", summary)
        self.write_text("README.md", readme)
        self.write_json(
            "schema.json",
            {"schema_version": SCHEMA_VERSION, "tables": list(TABLE_NAMES), "encoding": self.encoding},
        )

        incomplete = self.partial / ".incomplete"
        if incomplete.exists():
            incomplete.unlink()

        self.output_dir.mkdir(parents=True, exist_ok=True)
        if self.final.exists():
            import shutil

            shutil.rmtree(self.final)
        self.partial.rename(self.final)
        return self.final
