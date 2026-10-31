#!/usr/bin/env python3
"""
Nightly DigitalOcean droplet snapshot with rolling retention.

Creates a snapshot named auto_backup_YYYY-MM-DD_HHMM (US Eastern), waits for the
droplet action to complete, then deletes the oldest auto_backup_* snapshots until
at most AUTO_BACKUP_KEEP (default 5) remain.

Also deletes deploy pre-update snapshots (``rec-io-prod-pre-update-*``) whose
``created_at`` is older than PRE_UPDATE_SNAPSHOT_KEEP_DAYS (default 7).

Env:
  DIGITALOCEAN_API_TOKEN  required (or loaded from project .env)
  DO_PROD_DROPLET_ID      default 562337636
  AUTO_BACKUP_KEEP        default 5
  PRE_UPDATE_SNAPSHOT_KEEP_DAYS  default 7 (0 disables pre-update prune)
  AUTO_BACKUP_DRY_RUN=1   create skipped; prune printed only
  AUTO_BACKUP_SKIP_CREATE=1  prune only (no new snapshot)
  AUTO_BACKUP_WAIT_SEC    max seconds to wait for create (default 3600)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

API_BASE = "https://api.digitalocean.com/v2"
DEFAULT_DROPLET_ID = "562337636"
NAME_PREFIX = "auto_backup_"
PRE_UPDATE_PREFIX = "rec-io-prod-pre-update-"
EASTERN = ZoneInfo("America/New_York")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_token_from_dotenv() -> Optional[str]:
    env_path = _project_root() / ".env"
    if not env_path.is_file():
        return None
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("DIGITALOCEAN_API_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _token() -> str:
    tok = (os.environ.get("DIGITALOCEAN_API_TOKEN") or "").strip()
    if not tok:
        tok = (_load_token_from_dotenv() or "").strip()
    if not tok:
        raise SystemExit(
            "DIGITALOCEAN_API_TOKEN not set. Set it in the environment or project .env."
        )
    return tok


def _api(
    method: str,
    path: str,
    token: str,
    body: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, str]] = None,
) -> tuple[int, Any]:
    url = f"{API_BASE}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            code = resp.getcode()
            if not raw:
                return code, None
            return code, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DO API {method} {path} -> HTTP {e.code}: {err_body}") from e


def _backup_name_now() -> str:
    now = datetime.now(EASTERN)
    return f"{NAME_PREFIX}{now.strftime('%Y-%m-%d_%H%M')}"


def _list_droplet_snapshots(token: str) -> List[Dict[str, Any]]:
    page = 1
    out: List[Dict[str, Any]] = []
    while True:
        _code, payload = _api(
            "GET",
            "/snapshots",
            token,
            query={
                "resource_type": "droplet",
                "per_page": "200",
                "page": str(page),
            },
        )
        batch = (payload or {}).get("snapshots") or []
        out.extend(batch)
        total = int(((payload or {}).get("meta") or {}).get("total") or len(out))
        if len(out) >= total or not batch:
            break
        page += 1
    return out


def _auto_backups(snapshots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    autos = [
        s
        for s in snapshots
        if isinstance(s.get("name"), str) and s["name"].startswith(NAME_PREFIX)
    ]
    autos.sort(key=lambda s: (s.get("created_at") or "", str(s.get("id") or "")))
    return autos


def _pre_update_snapshots(snapshots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = [
        s
        for s in snapshots
        if isinstance(s.get("name"), str) and s["name"].startswith(PRE_UPDATE_PREFIX)
    ]
    rows.sort(key=lambda s: (s.get("created_at") or "", str(s.get("id") or "")))
    return rows


def _parse_created_at(raw: Any) -> Optional[datetime]:
    """Parse DO snapshot created_at (ISO-8601, usually …Z) to aware UTC datetime."""
    if not raw:
        return None
    s = str(raw).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _create_snapshot(token: str, droplet_id: str, name: str) -> int:
    _code, payload = _api(
        "POST",
        f"/droplets/{droplet_id}/actions",
        token,
        body={"type": "snapshot", "name": name},
    )
    action = (payload or {}).get("action") or {}
    action_id = action.get("id")
    if action_id is None:
        raise RuntimeError(f"snapshot create response missing action.id: {payload}")
    status = action.get("status")
    print(f"snapshot action submitted: id={action_id} status={status} name={name}")
    return int(action_id)


def _wait_action(
    token: str, droplet_id: str, action_id: int, wait_sec: int
) -> Dict[str, Any]:
    deadline = time.time() + wait_sec
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        _code, payload = _api(
            "GET", f"/droplets/{droplet_id}/actions/{action_id}", token
        )
        last = (payload or {}).get("action") or {}
        status = last.get("status")
        print(f"  action {action_id} status={status}")
        if status == "completed":
            return last
        if status == "errored":
            raise RuntimeError(f"snapshot action {action_id} errored: {last}")
        time.sleep(15)
    raise TimeoutError(
        f"snapshot action {action_id} not completed within {wait_sec}s; last={last}"
    )


def _delete_snapshot(token: str, snapshot_id: Any) -> None:
    sid = str(snapshot_id)
    code, _payload = _api("DELETE", f"/snapshots/{sid}", token)
    if code not in (204, 200):
        raise RuntimeError(f"unexpected delete status {code} for snapshot {sid}")
    print(f"deleted snapshot id={sid}")


def _prune_auto_backups(token: str, keep: int, dry_run: bool) -> None:
    autos = _auto_backups(_list_droplet_snapshots(token))
    print(f"auto_backup snapshots: {len(autos)} (keep={keep})")
    for s in autos:
        print(f"  {s.get('id')}\t{s.get('name')}\t{s.get('created_at')}")
    excess = len(autos) - keep
    if excess <= 0:
        print("no auto_backup prune needed")
        return
    to_delete = autos[:excess]
    for s in to_delete:
        print(
            f"{'DRY_RUN would delete' if dry_run else 'pruning'}: "
            f"id={s.get('id')} name={s.get('name')} created_at={s.get('created_at')}"
        )
        if not dry_run:
            _delete_snapshot(token, s.get("id"))


def _prune_old_pre_update(
    token: str, keep_days: int, dry_run: bool, *, now: Optional[datetime] = None
) -> None:
    """Delete ``rec-io-prod-pre-update-*`` snapshots older than keep_days."""
    if keep_days <= 0:
        print("pre-update prune disabled (PRE_UPDATE_SNAPSHOT_KEEP_DAYS<=0)")
        return
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    cutoff = now - timedelta(days=keep_days)
    rows = _pre_update_snapshots(_list_droplet_snapshots(token))
    print(
        f"pre-update snapshots: {len(rows)} "
        f"(delete created_at < {cutoff.isoformat()}, keep_days={keep_days})"
    )
    to_delete: List[Dict[str, Any]] = []
    for s in rows:
        created = _parse_created_at(s.get("created_at"))
        age_note = s.get("created_at")
        if created is None:
            print(
                f"  skip (unparseable created_at): id={s.get('id')} "
                f"name={s.get('name')} created_at={age_note}"
            )
            continue
        print(f"  {s.get('id')}\t{s.get('name')}\t{age_note}")
        if created < cutoff:
            to_delete.append(s)
    if not to_delete:
        print("no pre-update prune needed")
        return
    for s in to_delete:
        print(
            f"{'DRY_RUN would delete' if dry_run else 'pruning pre-update'}: "
            f"id={s.get('id')} name={s.get('name')} created_at={s.get('created_at')}"
        )
        if not dry_run:
            _delete_snapshot(token, s.get("id"))


def main() -> int:
    droplet_id = (os.environ.get("DO_PROD_DROPLET_ID") or DEFAULT_DROPLET_ID).strip()
    keep = int(os.environ.get("AUTO_BACKUP_KEEP") or "5")
    pre_update_keep_days = int(
        os.environ.get("PRE_UPDATE_SNAPSHOT_KEEP_DAYS") or "7"
    )
    wait_sec = int(os.environ.get("AUTO_BACKUP_WAIT_SEC") or "3600")
    dry_run = os.environ.get("AUTO_BACKUP_DRY_RUN", "").strip() == "1"
    skip_create = os.environ.get("AUTO_BACKUP_SKIP_CREATE", "").strip() == "1"

    if keep < 1:
        raise SystemExit("AUTO_BACKUP_KEEP must be >= 1")
    if pre_update_keep_days < 0:
        raise SystemExit("PRE_UPDATE_SNAPSHOT_KEEP_DAYS must be >= 0")

    token = _token()
    name = _backup_name_now()
    print(
        f"do_auto_backup: droplet={droplet_id} keep={keep} "
        f"pre_update_keep_days={pre_update_keep_days} "
        f"dry_run={dry_run} skip_create={skip_create} name={name}"
    )

    if not skip_create and not dry_run:
        action_id = _create_snapshot(token, droplet_id, name)
        _wait_action(token, droplet_id, action_id, wait_sec)
        # Brief settle so the new snapshot appears in /v2/snapshots.
        for _ in range(12):
            autos = _auto_backups(_list_droplet_snapshots(token))
            if any(s.get("name") == name for s in autos):
                print(f"confirmed new snapshot present: {name}")
                break
            time.sleep(5)
        else:
            print(
                f"warning: snapshot name {name} not yet visible in list; "
                "proceeding to prune anyway",
                file=sys.stderr,
            )
    elif dry_run and not skip_create:
        print(f"DRY_RUN: would create snapshot name={name}")
    else:
        print("skipping create")

    _prune_auto_backups(token, keep=keep, dry_run=dry_run)
    _prune_old_pre_update(token, keep_days=pre_update_keep_days, dry_run=dry_run)
    print("do_auto_backup: done")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"do_auto_backup FAILED: {e}", file=sys.stderr)
        raise SystemExit(1)
