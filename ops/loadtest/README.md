# Prod E2E + load-test harness

Controlled validation of the deployed backend. **Test tooling** — run manually
against prod with explicit args. Creates `@matilatest.local` Firebase users +
DB rows; **always isolate with a pre-test backup and restore-to-wipe afterward**
(see `docs/RESTORE.md`). Results + findings live in `docs/AZURE_PROVISION_LOG.md`
(Phase G).

Token minting needs the Firebase service account, so `vm_*.py` run **on the VM**;
`e2e.py` / `loadtest.py` run from a **workstation** over real HTTPS/wss (keeps the
1 GB box uncontended and the prod venv clean — the clients need `aiohttp` +
`websockets`).

## Scripts
- **`vm_mint.py`** (VM) — mint Firebase ID tokens for given emails →
  `{email:{uid,idToken}}`. `--api-key <FirebaseWebAPIKey> --emails a@x,b@x --out f.json`
- **`vm_provision_load.py`** (VM, prod env sourced, `PYTHONPATH=/opt/matila`) —
  create N pre-APPROVED onboarded users (alternating gender, complementary prefs)
  + mint tokens → `[{email,uid,idToken,gender}]`. `--api-key K --count N --out f.json`
- **`e2e.py`** (workstation) — drive the full frozen journey for 2 users + admin
  (bootstrap → onboard → verify → admin-approve → match → wss messaging → reveal-
  eligibility → report → rating). `python e2e.py tokens.json`
- **`loadtest.py`** (workstation) — N users join matchmaking, open wss, exchange
  messages for a duration; reports match/WS-connect rates, ack RTT, errors.
  `python loadtest.py users.json --users N --duration 60 --ramp 60`

## Typical run
```
# 1) pre-test backup (restore point)
ssh vm 'sudo systemctl start matila-backup.service'   # note the newest backups/ blob

# 2) provision + fetch tokens (on VM, prod env sourced, PYTHONPATH=/opt/matila)
ssh vm '.../python ops/loadtest/vm_provision_load.py --api-key K --count 100 --out /tmp/u.json'
scp vm:/tmp/u.json .

# 3) load test (workstation)
python ops/loadtest/loadtest.py u.json --users 100 --duration 60 --ramp 15

# 4) teardown — restore DB from the pre-test dump + delete @matilatest.local Firebase users
```

## Findings (2026-08-19)
100 concurrent = comfortable (100% success, ack-RTT p95 109 ms). 1000 collapses —
Postgres `max_connections=30` is the first ceiling, then Daphne saturates. Scaling
levers in `docs/STASH.md #6`.
