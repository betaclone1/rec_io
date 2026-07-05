"""Admin / operator HTTP endpoints (supervisor, shell-ish commands, logs, backups)."""

from __future__ import annotations

import os
import shlex
import subprocess
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from backend.core.tenant_context import resolved_tenant_user_no_for_app
from backend.web.auth_routes import _session_is_master_admin

from backend.util.paths import (
    get_dynamic_project_root,
    get_project_root,
    get_supervisor_config_path,
    get_supervisorctl_path,
)

admin_router = APIRouter(tags=["admin"])


def _require_master_admin() -> JSONResponse | None:
    u = resolved_tenant_user_no_for_app()
    if not _session_is_master_admin(u):
        return JSONResponse(status_code=403, content={"error": "Forbidden"})
    return None


@admin_router.post("/api/admin/supervisor-status")
async def get_supervisor_status():
    """Execute supervisorctl status command and return output"""
    try:
        project_dir = get_dynamic_project_root()
        supervisorctl_path = get_supervisorctl_path()
        supervisor_config_path = get_supervisor_config_path()

        os.chdir(project_dir)
        env = os.environ.copy()

        result = subprocess.run(
            [supervisorctl_path, "-c", supervisor_config_path, "status"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
            cwd=project_dir,
        )

        if result.stdout.strip():
            return {
                "success": True,
                "output": result.stdout,
            }
        return {
            "success": False,
            "error": f"Command failed with return code {result.returncode}",
            "output": result.stderr,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Command timed out",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@admin_router.post("/api/admin/execute-restart")
async def execute_restart():
    """Execute the restart script in background"""
    try:
        project_dir = get_dynamic_project_root()
        os.chdir(project_dir)

        env = os.environ.copy()
        env["PATH"] = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"

        subprocess.Popen(
            ["/bin/bash", "./scripts/restart"],
            cwd=project_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        return {
            "success": True,
            "message": "Restart script initiated in background",
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@admin_router.post("/api/admin/execute-command")
async def execute_command(request: Dict[str, Any]):
    """Execute arbitrary command at project level"""
    try:
        command = request.get("command", "")
        if not command:
            return {"success": False, "error": "No command provided"}

        project_dir = get_dynamic_project_root()
        supervisorctl_path = get_supervisorctl_path()
        supervisor_config_path = get_supervisor_config_path()

        os.chdir(project_dir)

        env = os.environ.copy()
        if "package_user_data.sh" not in command:
            env["PATH"] = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"

        if command.startswith("supervisorctl"):
            parts = command.split()
            if len(parts) >= 2:
                action = parts[1]
                if len(parts) >= 3:
                    script_name = parts[2]
                    result = subprocess.run(
                        [supervisorctl_path, "-c", supervisor_config_path, action, script_name],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=env,
                        cwd=project_dir,
                    )
                else:
                    result = subprocess.run(
                        [supervisorctl_path, "-c", supervisor_config_path, action],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=env,
                        cwd=project_dir,
                    )
            else:
                return {"success": False, "error": "Invalid supervisorctl command"}
        else:
            timeout = 300 if "package_user_data.sh" in command else 30
            if "package_user_data.sh" in command:
                run_cmd = ["/bin/bash", "-l", "-c", f"cd {shlex.quote(project_dir)} && {command}"]
                backup_env = env.copy()
                extra_paths = "/opt/homebrew/bin:/usr/local/bin:/usr/bin"
                backup_env["PATH"] = (backup_env.get("PATH") or "") + ":" + extra_paths
                result = subprocess.run(
                    run_cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=project_dir,
                    env=backup_env,
                )
            else:
                result = subprocess.run(
                    command.split(),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=env,
                    cwd=project_dir,
                )

        if result.returncode == 0:
            return {"success": True, "output": result.stdout}
        err_detail = (result.stderr or "").strip() or (result.stdout or "").strip()
        err_msg = f"Command failed with return code {result.returncode}"
        if err_detail:
            err_msg += f". {err_detail[:500]}"
        return {"success": False, "error": err_msg, "output": result.stderr or result.stdout}

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out after 5 minutes"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@admin_router.post("/api/admin/get-log-stream")
async def get_log_stream(request: Dict[str, Any]):
    """Stream log output for a specific script."""
    denied = _require_master_admin()
    if denied is not None:
        return denied

    script_name = request.get("script", "")
    log_type = request.get("logType", "out")

    if not script_name:
        return {"success": False, "error": "No script name provided"}

    project_dir = get_project_root()

    if log_type == "combined":
        log_files = []
        for suffix in [".out.log", ".err.log", ".log"]:
            potential_file = f"logs/{script_name}{suffix}"
            if os.path.exists(os.path.join(project_dir, potential_file)):
                log_files.append(potential_file)

        if not log_files:
            return {"success": False, "error": f"No log files found for {script_name}"}

        log_file = log_files[0]
    else:
        log_file = f"logs/{script_name}.{log_type}.log"
        if not os.path.exists(os.path.join(project_dir, log_file)):
            log_file = f"logs/{script_name}.log"

        if script_name == "auto_entry_supervisor" and log_type == "out":
            dedicated_log = f"logs/{script_name}.log"
            if os.path.exists(os.path.join(project_dir, dedicated_log)):
                log_file = dedicated_log

    if not os.path.exists(os.path.join(project_dir, log_file)):
        return {"success": False, "error": f"Log file not found: {log_file}"}

    def generate_log_stream():
        try:
            env = os.environ.copy()
            env["PATH"] = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"

            try:
                result = subprocess.run(
                    ["/usr/bin/tail", "-n", "100", log_file],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=project_dir,
                    env=env,
                )
                if result.returncode == 0 and result.stdout:
                    yield "=== Last 100 lines of log ===\n"
                    yield result.stdout
                    yield "\n=== Live tail starting ===\n"
            except Exception as e:
                yield f"Warning: Could not read existing log content: {str(e)}\n"
                yield "=== Starting live tail ===\n"

            process = subprocess.Popen(
                ["tail", "-f", log_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=project_dir,
                env=env,
                bufsize=1,
            )

            while True:
                line = process.stdout.readline()
                if not line:
                    break
                yield line.encode("utf-8").decode("utf-8")

        except Exception as e:
            yield f"Error: {str(e)}\n"
        finally:
            if "process" in locals():
                process.terminate()

    return StreamingResponse(
        generate_log_stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked",
        },
    )


@admin_router.post("/api/admin/create-backup")
async def create_backup():
    """Create a database backup using the package_user_data.sh script."""
    try:
        project_dir = get_dynamic_project_root()

        env = os.environ.copy()
        env["PATH"] = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"

        result = subprocess.run(
            ["bash", "scripts/backup/package_user_data.sh"],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            cwd=project_dir,
        )

        if result.returncode == 0:
            output = result.stdout
            backup_match = output.find("user_data_package_")
            if backup_match != -1:
                lines = output.split("\n")
                for line in lines:
                    if "user_data_package_" in line and ".tar.gz" in line:
                        backup_file = line.strip()
                        if backup_file.endswith(".tar.gz"):
                            backup_path = os.path.join(project_dir, "backup", backup_file)
                            if os.path.exists(backup_path):
                                try:
                                    from backend.util.master_system_log import log_system_event

                                    log_system_event(
                                        category="BACKUP",
                                        message=f"Database backup created: {backup_file}",
                                        source="admin_routes",
                                        severity="info",
                                        detail_ref="main_app",
                                        metadata={"backup_file": backup_file},
                                    )
                                except Exception:
                                    pass
                                return {
                                    "success": True,
                                    "output": output,
                                    "backup_file": backup_file,
                                    "backup_path": backup_path,
                                }

            return {"success": True, "output": output}
        return {
            "success": False,
            "error": f"Backup script failed with return code {result.returncode}",
            "output": result.stderr,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Backup timed out after 2 minutes"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@admin_router.post("/api/admin/download-file")
async def download_file(request: Dict[str, Any]):
    """Download a file from the server."""
    try:
        file_path = request.get("file_path", "")
        if not file_path:
            file_name = request.get("file", "").strip()
            if file_name:
                project_dir = get_project_root()
                file_path = os.path.join(project_dir, "backup", file_name)
            else:
                return {"success": False, "error": "No file path or file name provided"}
        project_dir = get_project_root()
        file_path = os.path.abspath(file_path)

        if not file_path.startswith(project_dir):
            return {"success": False, "error": "Access denied: File path outside project directory"}

        if not os.path.exists(file_path):
            return {"success": False, "error": "File not found"}

        if not os.path.isfile(file_path):
            return {"success": False, "error": "Path is not a file"}

        return FileResponse(
            path=file_path,
            filename=os.path.basename(file_path),
            media_type="application/octet-stream",
        )

    except Exception as e:
        return {"success": False, "error": str(e)}


@admin_router.get("/api/admin/download-file")
async def download_file_get(file: str):
    """Download a file from the server via GET request."""
    try:
        if not file:
            return {"success": False, "error": "No file name provided"}

        project_dir = get_project_root()
        backup_dir = os.path.join(project_dir, "backup")
        file_path = os.path.join(backup_dir, file)
        file_path = os.path.abspath(file_path)

        if not file_path.startswith(backup_dir):
            return {"success": False, "error": "Access denied: File path outside backup directory"}

        if not os.path.exists(file_path):
            return {"success": False, "error": "File not found"}

        if not os.path.isfile(file_path):
            return {"success": False, "error": "Path is not a file"}

        return FileResponse(
            path=file_path,
            filename=file,
            media_type="application/octet-stream",
        )

    except Exception as e:
        return {"success": False, "error": str(e)}
