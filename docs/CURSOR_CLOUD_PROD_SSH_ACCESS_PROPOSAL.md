# Cursor Cloud production SSH access proposal

## Summary

Cursor Cloud agents currently cannot run production SSH workflows such as
`/simple-pull` because the Cloud VM does not have an SSH private key accepted by
the production server:

```text
root@165.22.13.146: Permission denied (publickey)
```

Desktop agents likely work because they inherit a local workstation SSH identity.
Cloud agents run on separate infrastructure, so they need a dedicated SSH key
configured through Cursor Cloud secrets and authorized on the production host.

## Goals

- Let Cursor Cloud agents run existing production scripts:
  - `./scripts/prod/rec_prod_ssh.sh '...'`
  - `./scripts/prod/simple_git_pull_on_prod.sh`
  - restart/update workflows that SSH into `/opt/rec_io_server`
- Keep secrets out of git, chat, logs, and docs.
- Make access revocable by removing one public key from production.
- Preserve the current production host convention in `docs/PRODUCTION_HOST.md`.

## Non-goals

- Do not store private keys in this repository.
- Do not broaden production database permissions.
- Do not change live trading behavior or deployment flow as part of this setup.

## Current production target

Canonical production host details are in `docs/PRODUCTION_HOST.md`.

- SSH host: `165.22.13.146`
- Repo path: `/opt/rec_io_server`
- Expected env var: `REC_PROD_SSH_HOST`

The default SSH user is **`root`** (override with **`REC_PROD_SSH_USER`**). Example:

```bash
./scripts/prod/rec_prod_ssh.sh 'cd /opt/rec_io_server && git status -sb'
```

## Recommended path: dedicated deploy user

This is the safer long-term option. It avoids handing Cloud agents full root SSH
while still allowing controlled deployment operations.

### Server-side steps

Run these on production from an already authorized admin session.

1. Create a deploy user:

   ```bash
   sudo adduser --disabled-password --gecos "" recio_deploy
   sudo usermod -aG sudo recio_deploy
   ```

2. Authorize the Cursor Cloud public key:

   ```bash
   sudo install -d -m 700 -o recio_deploy -g recio_deploy /home/recio_deploy/.ssh
   echo 'ssh-ed25519 AAAA... cursor-cloud-prod' | sudo tee -a /home/recio_deploy/.ssh/authorized_keys
   sudo chown recio_deploy:recio_deploy /home/recio_deploy/.ssh/authorized_keys
   sudo chmod 600 /home/recio_deploy/.ssh/authorized_keys
   ```

3. Allow the deploy user to operate the repo:

   ```bash
   sudo chown -R recio_deploy:recio_deploy /opt/rec_io_server
   ```

4. If restart workflows require privileged commands, add narrow sudo rules with
   `sudo visudo -f /etc/sudoers.d/recio_deploy`:

   ```text
   recio_deploy ALL=(root) NOPASSWD: /bin/systemctl restart supervisor
   recio_deploy ALL=(root) NOPASSWD: /bin/systemctl reload supervisor
   recio_deploy ALL=(root) NOPASSWD: /usr/bin/supervisorctl *
   recio_deploy ALL=(root) NOPASSWD: /opt/rec_io_server/scripts/MASTER_RESTART.sh *
   ```

   Adjust paths after checking the actual command paths with `command -v`.

5. **Repo scripts (done in tree):** `scripts/prod/rec_prod_ssh.sh` reads **`REC_PROD_SSH_USER`** (default **`root`**) and **`REC_PROD_SSH_BATCH_MODE`** (`1` / `true` / `yes` adds **`BatchMode=yes`** for non-interactive agents). All wrappers that `exec` this script inherit the same env.

6. Set Cloud env:

   ```bash
   REC_PROD_SSH_HOST=165.22.13.146
   REC_PROD_SSH_USER=recio_deploy
   REC_PROD_SSH_BATCH_MODE=1
   ```

## Least-change path: authorize root key

This is fastest because scripts default to **`root`**. It grants broader
access, so use a dedicated key that can be revoked independently. Override with **`REC_PROD_SSH_USER`** for a deploy user once the server is set up.

### Server-side steps

Run these on production from an already authorized admin session.

1. Add the Cursor Cloud public key to root:

   ```bash
   sudo install -d -m 700 /root/.ssh
   echo 'ssh-ed25519 AAAA... cursor-cloud-prod' | sudo tee -a /root/.ssh/authorized_keys
   sudo chmod 600 /root/.ssh/authorized_keys
   sudo chown -R root:root /root/.ssh
   ```

2. Confirm SSH daemon config allows key-based root login:

   ```bash
   sudo sshd -t
   sudo systemctl reload ssh
   ```

   Relevant `sshd_config` settings:

   ```text
   PubkeyAuthentication yes
   AuthorizedKeysFile .ssh/authorized_keys
   PermitRootLogin prohibit-password
   ```

   `PermitRootLogin prohibit-password` allows SSH-key root login while disabling
   password root login.

## Cursor Cloud-side setup

The private key must be stored as a Cursor Cloud secret, not committed to git.

Suggested secret name:

```text
REC_PROD_SSH_PRIVATE_KEY
```

Startup setup should write it to `~/.ssh/id_ed25519`:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
printf '%s\n' "$REC_PROD_SSH_PRIVATE_KEY" > ~/.ssh/id_ed25519
chmod 600 ~/.ssh/id_ed25519
ssh-keyscan -H "$REC_PROD_SSH_HOST" >> ~/.ssh/known_hosts
chmod 644 ~/.ssh/known_hosts
```

If using the deploy-user path, also export:

```bash
export REC_PROD_SSH_USER=recio_deploy
```

## Verification

From a Cursor Cloud agent (after `REC_PROD_SSH_HOST` and optional `REC_PROD_SSH_USER` / `REC_PROD_SSH_BATCH_MODE` are exported), run:

```bash
export REC_PROD_SSH_BATCH_MODE=1
./scripts/prod/rec_prod_ssh.sh 'hostname && cd /opt/rec_io_server && git status --short --branch'
```

Then verify the repo wrapper:

```bash
./scripts/prod/simple_git_pull_on_prod.sh
```

Expected outcomes:

- SSH does not prompt for a password.
- The command reaches `/opt/rec_io_server`.
- `simple_git_pull_on_prod.sh` reports either `Already up to date` or a fast-forward pull.

## Rollback / revocation

Remove the Cursor Cloud public key from the relevant `authorized_keys` file:

```bash
sudo sed -i '/cursor-cloud-prod/d' /root/.ssh/authorized_keys
```

or, for deploy user:

```bash
sudo sed -i '/cursor-cloud-prod/d' /home/recio_deploy/.ssh/authorized_keys
```

Then remove or rotate the matching Cursor Cloud secret.

## Open decision

Choose one access model:

1. **Least-change root key:** fastest, matches current scripts, broadest access.
2. **Deploy user:** safer, requires a small script update and sudo policy review.

The recommended production-hardening path is deploy user. If operational speed is
the priority, root key access can be used first and replaced later.
