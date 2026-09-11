# Data Erasure Runbook (DPDP / GDPR right to erasure)

Matila honours data-deletion requests on demand. Users email the published
privacy contact; an admin verifies the request and runs the erasure command.

## Process (operational)
1. Request arrives at the privacy contact email (published in the privacy policy
   and the in-app "Delete my data" screen).
2. **Verify the requester** — confirm the request comes from the account's own
   email (or another agreed identity check) so one user can't delete another's data.
3. Run the command (below) **within the legal deadline** — GDPR: without undue
   delay, ≤ 30 days; DPDP: promptly.
4. The command writes an `audit_logs` entry (`action = user.erased`) as proof.

## Command
```bash
# on the VM, prod env sourced:
./.venv/bin/python manage.py erase_user --email someone@college.edu
#   --user-id <uuid>   erase by id instead of email
#   --yes              skip the interactive confirmation (for scripting)
#   --by ops@matila.in who ran it (recorded in the audit log)
```
Irreversible. Interactive mode asks you to re-type the user's email to confirm.

## What it does
**Hard-deleted** (the person's own data): profile fields + photo, all messages
they sent (+ image media in Blob), verification documents (college ID + gesture
selfie, in Blob), device/push tokens, notifications, matchmaking + reveal records,
ratings they authored. The **Firebase Auth identity** is deleted too.

**Retained but anonymized** (mandatory financial retention / platform-safety legal
basis, PII removed): the **payment ledger** (amounts/timestamps for tax law) and
**abuse reports**. These reference the user row via PROTECT keys, so the row is not
hard-deleted — instead every identifying field on it is scrubbed
(`firebase_uid`, `college_email`, name, photo, gender, intent, preferences),
`account_status = DELETED`. The remaining records point at a PII-free row.

## Notes
- Shared chats: only the erased user's messages + participation are removed; the
  other participant's side is kept (the erased user shows as a deleted/blank user).
- Verification documents of **non-erasing** users are retained by design (proof of
  a real, human user / anti-fraud) — there is no automatic deletion timer.
