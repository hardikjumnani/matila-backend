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

### Cost so far
| Resource | ~ Monthly (24/7) |
|---|---|
| VM `B2ats_v2` | $0 (free allowance) |
| Static public IP | ~$3.65 |
| OS disk (Std SSD 30 GB) | ~$3.00 |
| **Running total** | **~$6.65/mo** → within $100 for the year |

### Remaining in Phase A
- **A.7** — prod Blob storage account + private `media` container (~$0.5/mo). *(dev `matiladevstore` stays separate.)*
- **A.8** — DNS: Cloudflare A-record → `52.140.127.181` (needed for TLS in Phase C).
- *(A.5 Postgres + A.6 Redis are self-hosted on the VM → folded into **Phase B** deploy.)*
