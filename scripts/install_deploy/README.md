# Install and deploy scripts

All installation and deployment scripts live here so the top-level `scripts/` folder stays minimal.

**Install / setup**
- `install_auto_startup_service.sh` — systemd service for MASTER_RESTART on boot (production).
- `install_first_boot_sanitization.sh` — first-boot sanitization service (snapshot droplets).
- `install_production_auto_startup.sh`, `install_simple_auto_startup.sh` — production/simple auto-start.
- `enable_auto_startup.sh`, `disable_auto_startup.sh` — toggle auto-start.
- `auto_startup_wrapper.sh` — wrapper used by systemd; calls `MASTER_RESTART_WITH_SANITIZATION_CHECK.sh`.
- `setup_first_boot_sanitization.sh`, `setup_welcome_message.sh` — first-boot and welcome setup.
- `first_boot_sanitize.sh` — optional first-boot wipe; **disabled unless** `REC_ENABLE_FIRST_BOOT_SANITIZE=1`. Setup/install helpers require `REC_ENABLE_FIRST_BOOT_SANITIZE_SETUP=1`.
- `collaborator_setup.sh` — collaborator/system setup.

**Deploy**
- `simple_deploy.sh` — deploy to a remote host.
- `clone_and_sanitize_droplet.sh` — clone and sanitize droplet.
- `restore_production_db.sh` — restore production DB.
- `final_testing_and_deployment.sh` — final testing and deployment.
- `block_new_deployment.sh` — guard to block new deployment until setup.
- `git_update_system.sh` — production sync (e.g. `./scripts/install_deploy/git_update_system.sh update`).

**Run from project root**, e.g.:
- `./scripts/install_deploy/collaborator_setup.sh`
- `./scripts/install_deploy/simple_deploy.sh <host>`
