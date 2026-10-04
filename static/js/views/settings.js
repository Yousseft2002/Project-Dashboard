// Settings dialog: computers feeding the tracker, the synced folder, the second-PC setup kit, AI model.
import { esc, ago, api, toast } from "../util.js";
import { icon } from "../icons.js";
import { state } from "../state.js";

export const machineLabel = (m) => (m === state.data?.settings.local_machine ? "This PC" : m);

/** "YTPC" / "Both PCs" tag for projects that aren't only on this PC. */
export function machineTag(p) {
  const ms = p.facts.machines || [];
  const local = state.data.settings.local_machine;
  if (ms.length > 1) return `<span class="pc-tag" title="${esc(ms.join(", "))}">${icon("layers", 11)}${ms.length} PCs</span>`;
  if (ms[0] && ms[0] !== local) return `<span class="pc-tag" title="Lives on ${esc(ms[0])}">${icon("cpu", 11)}${esc(ms[0])}</span>`;
  return "";
}

function machinesTable() {
  const ms = state.data.digital.machines;
  if (!ms.length) return `<p class="muted">No scans yet.</p>`;
  return `<table class="mtable"><thead><tr><th>Computer</th><th>Last scan</th><th>Projects</th><th>Source</th></tr></thead><tbody>${ms.map((m) => {
    const hrs = (Date.now() - new Date(m.scanned_at)) / 3600000;
    const stale = !m.local && hrs > 2;
    return `<tr><td><b>${esc(m.machine)}</b>${m.local ? ` <span class="pc-tag">this PC</span>` : ""}</td>
      <td class="${stale ? "soon" : ""}">${esc(ago(m.scanned_at))}${stale ? " · not syncing?" : ""}</td>
      <td>${m.projects}</td><td>${m.local ? "Rescan button" : "OneDrive sync"}</td></tr>`;
  }).join("")}</tbody></table>`;
}

let phone = null;   // /api/access, fetched when the dialog opens (PC only)

function phoneSection() {
  const a = phone;
  if (!a) return `<section><h3>Phone access</h3><p class="muted">Loading…</p></section>`;
  const on = a.enabled && a.running;
  return `<section class="access"><h3>Phone access</h3>
    <p class="${on ? "ok-line" : "muted"}">${icon(on ? "checkCircle" : "lock", 15)}${on ? "On. Your phone can connect while it is on the same Wi-Fi as this PC." : "Off. Nothing outside this PC can reach the tracker."}</p>
    ${a.error ? `<p class="warn-line">${esc(a.error)}</p>` : ""}
    ${a.openssl ? "" : `<p class="warn-line">OpenSSL wasn't found, which phone access needs for encryption. Install Git for Windows (it includes it).</p>`}
    <div class="row-actions"><button type="button" class="btn ${on ? "" : "primary"}" data-act="togglePhone" ${a.openssl || on ? "" : "disabled"}>${on ? "Turn off phone access" : "Turn on phone access"}</button></div>
    ${on ? `
      <ol class="steps-list">
        <li>On your phone, join the same Wi-Fi and open:${a.urls.map((u) => `<div class="mono access-url">${esc(u)}</div>`).join("") || " (no network address found)"}</li>
        <li>Your browser will warn that the certificate isn't trusted. That is expected: it was made on this PC. Check that the fingerprint below matches, then choose to continue.</li>
        <li>Enter this access code:<div class="access-code mono">${esc(a.code)}</div></li>
      </ol>
      <p class="muted small">Certificate fingerprint (SHA-256): <span class="mono access-fp">${esc(a.fingerprint)}</span></p>
      <p class="muted small">${a.sessions} phone${a.sessions === 1 ? "" : "s"} signed in. Windows may ask whether to let Python through the firewall: allow <b>Private networks</b> only.</p>
      <div class="row-actions">
        <button type="button" class="btn" data-act="newPhoneCode">New code (signs everyone out)</button>
        <button type="button" class="btn" data-act="signOutPhones" ${a.sessions ? "" : "disabled"}>Sign out all phones</button>
      </div>` : ""}
  </section>`;
}

function body() {
  const s = state.data.settings;
  if (state.data.access?.remote) {
    return `<div class="form settings">
      <div class="dlg-head"><h2>${icon("lock", 20)}Signed in</h2><button class="icon-x always" value="close" aria-label="Close">${icon("x", 16)}</button></div>
      <section><p class="muted">${state.data.access.cloud ? "You're using the protected cloud deployment. Local folders, scanning, previews, and computer sync require the local server." : "You're using Project Tracker from your phone. Sync settings and opening folders are only available on the PC."}</p>
      <div class="row-actions"><button type="button" class="btn" data-act="signOut">Sign out</button></div></section></div>`;
  }
  const others = state.data.digital.machines.filter((m) => !m.local);
  return `<div class="form settings">
    <div class="dlg-head"><h2>${icon("cpu", 20)}Computers & sync</h2><button class="icon-x always" value="close" aria-label="Close">${icon("x", 16)}</button></div>
    ${phoneSection()}
    <section><h3>Computers</h3>${machinesTable()}</section>
    <section><h3>Home PC (YTPC) setup</h3>
      ${others.length ? `<p class="ok-line">${icon("checkCircle", 15)}Receiving snapshots from ${others.map((m) => esc(m.machine)).join(", ")}.</p>` : ""}
      <ol class="steps-list">
        <li>Create the setup kit. It's saved in your synced folder, so OneDrive carries it to YTPC.</li>
        <li>On YTPC, open <b>OneDrive › ProjectTracker › ytpc-kit</b> and double-click <b>Install on this PC.cmd</b> (needs Python 3).</li>
        <li>YTPC scans every 30 minutes, and its projects appear here automatically. The same repo on both PCs shows as one project.</li>
      </ol>
      <div class="row-actions">
        <button type="button" class="btn primary" data-act="createKit" ${s.sync_dir ? "" : "disabled"}>${icon("rocket", 15)}${s.kit_ready ? "Update setup kit" : "Create setup kit"}</button>
        <button type="button" class="btn" data-act="openSync" ${s.sync_ok ? "" : "disabled"}>${icon("folder", 15)}Open synced folder</button>
      </div>
      ${s.kit_ready ? `<p class="muted small">${icon("checkCircle", 13)} Kit is ready in ${esc(s.sync_dir)}\\ytpc-kit</p>` : ""}
    </section>
    <section><h3>Synced folder</h3>
      <div class="inline-add"><input name="sync_dir" value="${esc(s.sync_dir)}" placeholder="e.g. C:\\Users\\you\\OneDrive\\ProjectTracker" aria-label="Synced folder">
        <button type="button" class="btn" data-act="saveSyncDir">Save</button></div>
      <p class="muted small">Any folder both PCs sync (OneDrive, Google Drive, Dropbox). Snapshots go in its <span class="mono">snapshots</span> subfolder.${s.sync_ok ? "" : " The folder will be created with the kit."}</p>
    </section>
  </div>`;
}

let dlg = null;
export function openSettings() {
  dlg?.remove();
  dlg = document.createElement("dialog");
  dlg.className = "settings-dlg";
  dlg.innerHTML = `<form method="dialog">${body()}</form>`;
  document.body.appendChild(dlg);
  dlg.showModal();
  if (!state.data.access?.remote && !state.data.access?.cloud) api("GET", "/api/access").then((a) => { phone = a; refresh(); }).catch(() => {});
  dlg.addEventListener("close", () => { dlg.remove(); dlg = null; });
}
function refresh() { if (dlg) dlg.querySelector("form").innerHTML = body(); }

export const settingsActions = {
  openSettings,
  async createKit() {
    const r = await api("POST", "/api/sync/kit");
    Object.assign(state.data.settings, r);
    refresh();
    toast("Setup kit saved to " + r.path);
  },
  async togglePhone() {
    try { phone = await api("POST", "/api/access", { enabled: !(phone.enabled && phone.running) }); }
    catch (e) { toast(e.message); phone = await api("GET", "/api/access"); }
    refresh();
  },
  async newPhoneCode() { if (confirm("Make a new code? Every phone will be signed out.")) { phone = await api("POST", "/api/access/code"); refresh(); toast("New code created"); } },
  async signOutPhones() { phone = await api("POST", "/api/access/revoke"); refresh(); toast("All phones signed out"); },
  async signOut() { await api("POST", "/api/logout").catch(() => {}); location.replace("/login"); },
  async openSync() { await api("POST", "/api/sync/open"); },
  async saveSyncDir() {
    const v = dlg.querySelector("input[name=sync_dir]").value;
    Object.assign(state.data.settings, await api("POST", "/api/settings", { sync_dir: v }));
    refresh();
    toast("Synced folder saved");
  },
};
