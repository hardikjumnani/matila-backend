# Azure Provisioning Log — Production

Audit trail of every Azure resource created for Matila production, with names,
costs, and reversal notes. Region **Central India**. Subscription **Azure for
Students** (`a774bdd0-f2cf-47bb-87bb-eb5bdb7e557d`). Cost-optimized for maximum
$100-credit runway: one free-tier VM runs everything (Postgres + Redis
self-hosted); see `docs/DEPLOYMENT_PLAN.md` / `docs/ROADMAP.md`.

**Reversal (tears down EVERYTHING below):** `az group delete -n matila-prod-rg --yes`

---

## Phase A — Provision (2026-08-13)

### A.1 — Preflight
- `az login` as `hardik.jumnani123@gmail.com`; subscription = **Azure for Students**.
- Registered resource providers **Microsoft.Compute** and **Microsoft.Network**
  (were `NotRegistered` on the fresh sub; Storage already registered). Free.
- Quota (Central India): **Total Regional vCPUs = 6**; Basv2 family = 10; BS = 4.
  → the 2-vCPU `B2ats_v2` fits (uses 2/6). Gate: **PASS**.

### A.2 — Resource group — **free**
- `matila-prod-rg` (centralindia).

### A.3 — Networking — **free**
- VNet `matila-prod-vnet` — `10.0.0.0/16`.
- Subnet `matila-prod-subnet` — `10.0.1.0/24`.
- NSG `matila-prod-nsg` (attached to the subnet). Inbound rules:
  | Rule | Port | Source | Prio |
  |---|---|---|---|
  | allow-ssh | 22 | `14.194.79.194/32` (owner's IP) | 100 |
  | allow-http | 80 | Internet | 110 |
  | allow-https | 443 | Internet | 120 |
  | (default) | * | denied | — |
  - ⚠️ SSH is locked to `14.194.79.194` (dynamic/residential IP). If it rotates,
    update: `az network nsg rule update -g matila-prod-rg --nsg-name matila-prod-nsg -n allow-ssh --source-address-prefixes <NEW_IP>/32`

### A.4 — VM + disk + IP — **first billable** (2026-08-13)
- Public IP `matila-prod-ip` — Standard, **Static** → **`52.140.127.181`**. ~$3.65/mo.
- NIC `matila-prod-nic` — no NIC-level NSG (subnet NSG governs). Free.
- VM `matila-prod-vm` — `Standard_B2ats_v2` (2 vCPU / **891 MB** usable), Ubuntu
  22.04.5 LTS (gen2), private IP `10.0.1.4`. **Free** (750-hr student allowance).
- OS disk `matila-prod-osdisk` — Standard SSD, 30 GB (`nic-delete`/`os-disk-delete`
  = Delete, so the VM tearing down cleans them up). ~$3/mo.
- SSH: `ssh azureuser@52.140.127.181`, key `~/.ssh/id_rsa` on the owner's machine
  (`C:\Users\hardi\.ssh\`). **Gate: SSH verified working. PASS.**
- No swap yet (added in Phase B for the 1 GB constraint).

### A.7 — Prod Blob storage (2026-08-13)
- Storage account `matilaprodstore` (Standard_LRS, StorageV2, TLS1_2,
  **`allowBlobPublicAccess=false`**). Private `media` container.
- Connection string is a **secret** — not stored here. Retrieve on demand for
  the Phase B env file: `az storage account show-connection-string -g matila-prod-rg -n matilaprodstore -o tsv`
- Dev `matiladevstore` remains separate/untouched.

### A.8 — DNS (free Azure hostname, Option A)
- DNS label set on `matila-prod-ip` → **`matila-prod.centralindia.cloudapp.azure.com`**
  → resolves to `52.140.127.181`. Used for Let's Encrypt TLS in Phase C.
- (A branded Cloudflare domain can be swapped in later; not required.)

### Cost so far
| Resource | ~ Monthly (24/7) |
|---|---|
| VM `B2ats_v2` | $0 (free allowance) |
| Static public IP | ~$3.65 |
| OS disk (Std SSD 30 GB) | ~$3.00 |
| Blob `matilaprodstore` (media, few GB) | ~$0.50 |
| Azure DNS label | free |
| **Running total** | **~$7.15/mo** → within $100 for the year |

### Phase A — COMPLETE ✅
Gate met: all infra deployed; SSH works (from owner IP only); NSG limited to
22/80/443; FQDN resolves. Postgres + Redis run **on the VM** (localhost-private
by construction) and are installed in **Phase B**, which is the next step.
