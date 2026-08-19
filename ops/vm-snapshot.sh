#!/usr/bin/env bash
#
# Weekly OS-disk snapshot for the Matila prod VM.
#
# Uses the VM's system-assigned MANAGED IDENTITY + the ARM REST API (no az CLI on
# the box, which would be heavy on the 1 GB VM). Creates an *incremental*
# snapshot (bills only changed blocks -> cheap) and prunes to the newest $KEEP.
# Scheduled by matila-vm-snapshot.timer. The identity holds a least-privilege
# custom role ("Matila Snapshot Manager": snapshots read/write/delete + disks
# read) scoped to the resource group.
#
set -euo pipefail

SUB="a774bdd0-f2cf-47bb-87bb-eb5bdb7e557d"
RG="matila-prod-rg"
LOCATION="centralindia"
DISK_ID="/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Compute/disks/matila-prod-osdisk"
PREFIX="matila-osdisk-"
KEEP=4
API="2023-04-02"
ARM="https://management.azure.com"

log() { echo "[vm-snapshot] $*"; }

# 1) Access token from the Instance Metadata Service (managed identity).
TOKEN=$(curl -s -H "Metadata: true" \
  "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fmanagement.azure.com%2F" \
  | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))")
[ -n "${TOKEN}" ] || { log "ERROR: failed to obtain IMDS token"; exit 1; }

# 2) Create an incremental snapshot of the OS disk.
SNAP="${PREFIX}$(date -u +%Y%m%d-%H%M%SZ)"
log "creating snapshot ${SNAP}"
curl -s -X PUT \
  -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
  "${ARM}/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Compute/snapshots/${SNAP}?api-version=${API}" \
  -d "{\"location\":\"${LOCATION}\",\"properties\":{\"creationData\":{\"createOption\":\"Copy\",\"sourceResourceId\":\"${DISK_ID}\"},\"incremental\":true}}" \
  | python3 -c "import sys,json
d=json.load(sys.stdin)
if 'error' in d:
    print('[vm-snapshot] ERROR', d['error']); sys.exit(1)
print('[vm-snapshot] created', d.get('name'), '->', d.get('properties',{}).get('provisioningState'))"

# 3) Prune: keep the newest ${KEEP} snapshots matching the prefix (names carry a
#    sortable UTC timestamp, so lexicographic sort == chronological).
log "pruning old snapshots (keep ${KEEP})"
TO_DELETE=$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${ARM}/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Compute/snapshots?api-version=${API}" \
  | python3 -c "import sys,json
d=json.load(sys.stdin)
snaps=sorted([s for s in d.get('value',[]) if s['name'].startswith('${PREFIX}')], key=lambda s:s['name'])
old=snaps[:-${KEEP}] if len(snaps)>${KEEP} else []
for s in old: print(s['id'])")

for sid in ${TO_DELETE}; do
  log "deleting ${sid##*/}"
  curl -s -X DELETE -H "Authorization: Bearer ${TOKEN}" \
    "${ARM}${sid}?api-version=${API}" -o /dev/null -w "[vm-snapshot] delete http=%{http_code}\n"
done

log "done"
