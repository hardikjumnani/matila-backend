"""
Local admin panel UI (DEV ONLY).

A self-contained single-page admin console served at ``/admin-panel/`` for local
review of verification applications (and a peek at reports/users) against the
existing ``/api/v1/admin/...`` API. Dev-only: the route is registered only when
DEBUG is on, and it authenticates via the dev-bypass ("dev:<email>") token, so it
never ships to production. The production-grade panel is a separate FE workstream.
"""

from __future__ import annotations

from django.http import HttpResponse, HttpResponseNotFound

_PANEL_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Matila Admin (dev)</title>
<style>
  :root { --bg:#0f1115; --panel:#171a21; --panel2:#1e222b; --line:#2a2f3a;
          --text:#e7e9ee; --muted:#9aa3b2; --accent:#4f9dff; --green:#2ecc71;
          --red:#ff5f6d; --amber:#ffb020; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:14px/1.5 system-ui,Segoe UI,Roboto,Arial,sans-serif; }
  header { display:flex; align-items:center; gap:12px; padding:12px 16px;
           background:var(--panel); border-bottom:1px solid var(--line); flex-wrap:wrap; }
  header h1 { font-size:16px; margin:0; margin-right:auto; }
  input, select, button, textarea { font:inherit; color:var(--text);
           background:var(--panel2); border:1px solid var(--line); border-radius:8px;
           padding:8px 10px; }
  button { cursor:pointer; }
  button.primary { background:var(--accent); border-color:var(--accent); color:#06101f; font-weight:600; }
  button.green { background:var(--green); border-color:var(--green); color:#06210f; font-weight:600; }
  button.red { background:var(--red); border-color:var(--red); color:#2a0608; font-weight:600; }
  button.amber { background:var(--amber); border-color:var(--amber); color:#241700; font-weight:600; }
  .wrap { display:grid; grid-template-columns:380px 1fr; gap:16px; padding:16px; }
  @media (max-width:800px){ .wrap { grid-template-columns:1fr; } }
  .col { background:var(--panel); border:1px solid var(--line); border-radius:12px;
         padding:12px; min-height:60vh; }
  .row { display:flex; align-items:center; gap:8px; }
  .muted { color:var(--muted); }
  .pill { font-size:11px; padding:2px 8px; border-radius:999px; border:1px solid var(--line); }
  .PENDING { color:var(--amber); border-color:var(--amber); }
  .APPROVED { color:var(--green); border-color:var(--green); }
  .REJECTED, .RESUBMISSION_REQUIRED { color:var(--red); border-color:var(--red); }
  .card { padding:10px 12px; border:1px solid var(--line); border-radius:10px;
          margin-bottom:8px; cursor:pointer; background:var(--panel2); }
  .card:hover { border-color:var(--accent); }
  .card.active { border-color:var(--accent); box-shadow:0 0 0 1px var(--accent) inset; }
  .imgs { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:12px 0; }
  .imgs figure { margin:0; }
  .imgs img { width:100%; border-radius:10px; border:1px solid var(--line); background:#000; aspect-ratio:4/3; object-fit:contain; }
  figcaption { font-size:12px; color:var(--muted); margin-bottom:6px; }
  textarea { width:100%; min-height:70px; resize:vertical; }
  .actions { display:flex; gap:8px; margin-top:10px; flex-wrap:wrap; }
  .kv { display:grid; grid-template-columns:120px 1fr; gap:4px 10px; font-size:13px; }
  .kv div:nth-child(odd){ color:var(--muted); }
  #toast { position:fixed; bottom:16px; right:16px; padding:10px 14px; border-radius:10px;
           background:var(--panel2); border:1px solid var(--line); opacity:0; transition:.2s; }
  #toast.show { opacity:1; }
  .empty { color:var(--muted); padding:24px; text-align:center; }
  code { background:var(--panel2); padding:1px 5px; border-radius:5px; }
</style>
</head>
<body>
<header>
  <h1>🛠️ Matila Admin <span class="muted" style="font-weight:400">· dev</span></h1>
  <input id="email" placeholder="admin email" style="width:260px"/>
  <button class="primary" onclick="login()">Sign in</button>
  <span id="who" class="muted"></span>
  <select id="status" onchange="loadList()">
    <option value="PENDING">Pending</option>
    <option value="RESUBMISSION_REQUIRED">Resubmission</option>
    <option value="APPROVED">Approved</option>
    <option value="REJECTED">Rejected</option>
    <option value="ALL">All</option>
  </select>
  <button onclick="loadList()">Refresh</button>
  <button onclick="loadColleges()">Colleges</button>
</header>

<div class="wrap">
  <div class="col">
    <div class="row" style="justify-content:space-between;margin-bottom:8px">
      <strong>Verification queue</strong><span id="count" class="muted"></span>
    </div>
    <div id="list"><div class="empty">Sign in to load applications.</div></div>
  </div>
  <div class="col" id="detail"><div class="empty">Select an application to review.</div></div>
</div>
<div id="toast"></div>

<script>
const API = "/api/v1";
let TOKEN = localStorage.getItem("matila_admin_token") || "";
let CURRENT = null;

function toast(msg, ok=true){
  const t=document.getElementById("toast"); t.textContent=msg;
  t.style.borderColor = ok ? "var(--green)" : "var(--red)";
  t.classList.add("show"); setTimeout(()=>t.classList.remove("show"), 2600);
}
function whoami(){
  const email = TOKEN.startsWith("dev:") ? TOKEN.slice(4) : (TOKEN ? "token set" : "");
  document.getElementById("who").textContent = email ? ("as "+email) : "";
}
function login(){
  const email=document.getElementById("email").value.trim();
  if(!email){ toast("enter an admin email", false); return; }
  TOKEN = "dev:"+email; localStorage.setItem("matila_admin_token", TOKEN);
  whoami(); loadList();
}
async function api(path, method="GET", body=null){
  const res = await fetch(API+path, {
    method,
    headers: { "Authorization":"Bearer "+TOKEN, "Content-Type":"application/json" },
    body: body ? JSON.stringify(body) : null,
  });
  const data = await res.json().catch(()=>({}));
  if(!res.ok){
    const code = (data.error && data.error.code) || res.status;
    throw new Error(code + (data.error && data.error.message ? " — "+data.error.message : ""));
  }
  return data.data !== undefined ? data.data : data;
}
async function loadList(){
  if(!TOKEN){ toast("sign in first", false); return; }
  const status=document.getElementById("status").value;
  try {
    const items = await api("/admin/verifications?status="+status);
    const list = Array.isArray(items) ? items : (items.items || items.results || []);
    document.getElementById("count").textContent = list.length + " item(s)";
    const el=document.getElementById("list");
    if(!list.length){ el.innerHTML='<div class="empty">No applications.</div>'; return; }
    el.innerHTML = list.map(r=>`
      <div class="card" id="c_${r.id}" onclick="openDetail('${r.id}')">
        <div class="row" style="justify-content:space-between">
          <strong>attempt #${r.attempt_number}</strong>
          <span class="pill ${r.status}">${r.status}</span>
        </div>
        <div class="muted" style="font-size:12px">user ${String(r.user_id).slice(0,8)}… ·
          ${r.submitted_at ? new Date(r.submitted_at).toLocaleString() : "—"}</div>
      </div>`).join("");
  } catch(e){ toast(e.message, false); }
}
async function openDetail(id){
  // Immediate feedback before the round-trip: highlight the card + show loading.
  document.querySelectorAll(".card").forEach(c=>c.classList.remove("active"));
  const card=document.getElementById("c_"+id); if(card) card.classList.add("active");
  document.getElementById("detail").innerHTML='<div class="empty">Loading…</div>';
  try {
    const r = await api("/admin/verifications/"+id);
    CURRENT = r;
    const canAct = r.status==="PENDING" || r.status==="RESUBMISSION_REQUIRED";
    document.getElementById("detail").innerHTML = `
      <div class="row" style="justify-content:space-between">
        <strong>Application review</strong><span class="pill ${r.status}">${r.status}</span>
      </div>
      <div class="imgs">
        <figure><figcaption>College ID</figcaption>
          <img src="${r.college_id_image_url||''}" alt="college id"
               onerror="this.style.opacity=.3;this.alt='image unavailable'"/></figure>
        <figure><figcaption>Gesture selfie — <code>${r.gesture_type||'?'}</code></figcaption>
          <img src="${r.gesture_selfie_image_url||''}" alt="selfie"
               onerror="this.style.opacity=.3;this.alt='image unavailable'"/></figure>
      </div>
      <div class="kv">
        <div>User</div><div>${r.user_id}</div>
        <div>Attempt</div><div>#${r.attempt_number}</div>
        <div>Submitted</div><div>${r.submitted_at? new Date(r.submitted_at).toLocaleString():"—"}</div>
        <div>Reviewed</div><div>${r.reviewed_at? new Date(r.reviewed_at).toLocaleString():"—"}</div>
        <div>Prev notes</div><div>${r.review_notes||"—"}</div>
      </div>
      <p class="muted" style="margin:12px 0 4px">Reviewer notes (optional)</p>
      <textarea id="notes" placeholder="reason / notes for the applicant"></textarea>
      <div class="actions">
        ${canAct ? `
          <button class="green" onclick="act('${r.id}','approve')">Approve</button>
          <button class="red" onclick="act('${r.id}','reject')">Reject</button>
          <button class="amber" onclick="act('${r.id}','request-resubmission')">Request resubmit</button>
        ` : `<span class="muted">Already reviewed — no actions.</span>`}
      </div>`;
  } catch(e){ toast(e.message, false); }
}
async function act(id, action){
  const notes=(document.getElementById("notes")||{}).value||"";
  // Disable the action row immediately so clicks feel instant and can't double-fire.
  const btns=[...document.querySelectorAll(".actions button")];
  btns.forEach(b=>{ b.disabled=true; });
  toast(action.replace("-"," ")+"…");
  try {
    await api("/admin/verifications/"+id+"/"+action, "POST", {notes});
    toast(action.replace("-"," ")+" ✓");
    await loadList(); await openDetail(id);
  } catch(e){ btns.forEach(b=>{ b.disabled=false; }); toast(e.message, false); }
}
// --- Colleges (launch-date management) ---
function toLocalInput(iso){
  if(!iso) return "";
  const d=new Date(iso); if(isNaN(d)) return "";
  const p=n=>String(n).padStart(2,"0");
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
async function loadColleges(){
  if(!TOKEN){ toast("sign in first", false); return; }
  try {
    const list = await api("/admin/colleges");
    const el=document.getElementById("detail");
    el.innerHTML = `<strong>Colleges</strong>
      <p class="muted" style="margin:6px 0 12px">Set each college's launch date — verified members enter the app at launch.</p>
      ${list.map(c=>`
        <div class="card" style="cursor:default">
          <div class="row" style="justify-content:space-between">
            <strong>${c.name}</strong>
            <span class="pill ${c.is_launched?'APPROVED':'PENDING'}">${c.is_launched?'LAUNCHED':'PRE-LAUNCH'}</span>
          </div>
          <div class="muted" style="font-size:12px">code <code>${c.code}</code> · ${c.user_count} user(s) ·
            ${(c.allowed_email_domains||[]).join(', ')||'no domains'}</div>
          <div class="row" style="margin-top:8px;gap:8px;flex-wrap:wrap">
            <input type="datetime-local" id="ld_${c.id}" value="${toLocalInput(c.launch_date)}"/>
            <button class="primary" onclick="saveLaunch('${c.id}')">Save launch</button>
            <button onclick="saveLaunch('${c.id}', true)">Unset</button>
          </div>
        </div>`).join("")}`;
  } catch(e){ toast(e.message, false); }
}
async function saveLaunch(id, clear=false){
  let launch_date=null;
  if(!clear){
    const v=(document.getElementById("ld_"+id)||{}).value;
    if(!v){ toast("pick a date or use Unset", false); return; }
    launch_date=new Date(v).toISOString();
  }
  try {
    await api("/admin/colleges/"+id, "PATCH", {launch_date});
    toast("launch date saved ✓");
    await loadColleges();
  } catch(e){ toast(e.message, false); }
}
// boot
document.getElementById("email").value = TOKEN.startsWith("dev:") ? TOKEN.slice(4) : "";
whoami(); if(TOKEN) loadList();
</script>
</body>
</html>
"""


def admin_panel_ui(request):
    """Serve the dev admin panel (only mounted when DEBUG is on)."""
    from django.conf import settings

    if not settings.DEBUG:
        return HttpResponseNotFound("Not available.")
    return HttpResponse(_PANEL_HTML, content_type="text/html; charset=utf-8")
