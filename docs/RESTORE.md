# Restore & Disaster Recovery Runbook

How to recover Matila prod. Two independent safety nets:

| What | Mechanism | Schedule | Retention | Location |
|---|---|---|---|---|
| **Database** | `pg_dump -Fc` → Azure Blob | nightly 02:30 IST / 21:00 UTC (`matila-backup.timer`) | 14 days (Blob lifecycle rule) | `matilaprodstore` / `backups/` |
| **Whole VM** | incremental OS-disk snapshot | weekly Sun 03:00 IST / Sat 21:30 UTC (`matila-vm-snapshot.timer`) | newest 4 | RG `matila-prod-rg`, `matila-osdisk-*` |

**Redis is NOT backed up** — it is an ephemeral cache / broker / channel layer and
rebuilds itself. After any restore, just ensure `redis-server` is running.

> Verified 2026-08-19: a Blob dump restored into a scratch DB with matching row
> counts and a clean `migrate --check`. Re-run the drill after major schema changes.

---

## A. Restore the database (from a nightly Blob dump)

On the VM (`/opt/matila`). Pick the dump you want (newest by default).

**1. Download the dump from Blob** (run via the app venv so the SDK is present;
read the connection string straight from the env file so the `;` isn't mangled):

```bash
CONN="$(grep '^AZURE_STORAGE_CONNECTION_STRING=' /etc/matila/env.production | cut -d= -f2-)"
CONN="$CONN" /opt/matila/.venv/bin/python - <<'PY'
import os
from azure.storage.blob import BlobServiceClient
svc = BlobServiceClient.from_connection_string(os.environ['CONN'])
c = svc.get_container_client('backups')
# newest; or set `latest = "<blob name>"` to pick a specific one
latest = sorted(c.list_blobs(), key=lambda b: b.last_modified)[-1].name
open('/tmp/restore.dump', 'wb').write(c.download_blob(latest).readall())
print('downloaded', latest)
PY
```

**2a. Inspect first (non-destructive) — restore into a scratch DB:**

```bash
sudo -u postgres dropdb --if-exists anonymous_chat_restore
sudo -u postgres createdb anonymous_chat_restore -O matila
sudo -u postgres pg_restore -d anonymous_chat_restore /tmp/restore.dump
sudo -u postgres psql -d anonymous_chat_restore -c "SELECT count(*) FROM users;"
```

**2b. Actual recovery (DESTRUCTIVE — replaces live data):** stop the app first so
nothing writes during the restore.

```bash
sudo systemctl stop matila-asgi matila-celery
sudo -u postgres dropdb anonymous_chat
sudo -u postgres createdb anonymous_chat -O matila
sudo -u postgres pg_restore -d anonymous_chat /tmp/restore.dump
sudo systemctl start matila-asgi matila-celery
```

**3. Verify:** `curl -s https://<FQDN>/health/ready` → 200; optionally
`set -a; . /etc/matila/env.production; set +a; ./.venv/bin/python manage.py migrate --check`.
Then delete `/tmp/restore.dump`.

Recovery point = the last nightly dump (up to ~24 h of writes could be lost — that
is the accepted MVP RPO; true PITR is stashed until there is real user data).

---

## B. Restore the whole VM (from an OS-disk snapshot)

For a corrupted/lost VM (recovers OS + config + code + certs, not just the DB).
Run from a workstation with `az` logged in.

```bash
RG=matila-prod-rg; LOC=centralindia
SNAP=$(az snapshot list -g $RG --query "sort_by([?starts_with(name,'matila-osdisk-')],&timeCreated)[-1].name" -o tsv)
SNAP_ID=$(az snapshot show -g $RG -n $SNAP --query id -o tsv)

# Create a managed disk from the snapshot
az disk create -g $RG -n matila-restored-osdisk --source "$SNAP_ID" --location $LOC

# Option 1: swap the OS disk on the existing VM
az vm stop -g $RG -n matila-prod-vm
az vm update -g $RG -n matila-prod-vm --os-disk matila-restored-osdisk
az vm start -g $RG -n matila-prod-vm
```

Then SSH in, confirm the core services (`matila-asgi`, `matila-celery`, `nginx`,
`postgresql`, `redis-server`) are active, and hit `/health/ready`. If the DB on the
snapshot is stale relative to the latest nightly dump, follow section A afterward.

---

## Notes
- Backups and snapshots are encrypted at rest by Azure (Storage + Managed Disk
  Storage Service Encryption). The `backups` container is private
  (`allowBlobPublicAccess=false`).
- The snapshot automation uses the VM's system-assigned managed identity + the
  custom role **"Matila Snapshot Manager"** (snapshots read/write/delete, disks
  read + begin/endGetAccess), scoped to `matila-prod-rg`.
