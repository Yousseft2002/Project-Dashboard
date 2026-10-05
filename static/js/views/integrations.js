import { esc, ago } from '../util.js';
import { state } from '../state.js';

export function timeline(events) {
  return events.length ? `<ol>${events.slice(0,100).map(e=>`<li><time>${esc(new Date(e.timestamp).toLocaleString())}</time> · <b>${esc(e.source)}</b> · ${esc(e.summary)} <span class="muted">${esc(e.device_id || '')}</span></li>`).join('')}</ol>` : '<p class="muted">No ingested activity yet.</p>';
}

export function sourcePanel() {
  const c = state.data.central;
  if (!c) return '';
  return `<section class="card" style="padding:20px;margin-bottom:20px"><h2>Data sources</h2>
    <p><a href="#/integrations">Settings → Integrations</a> · <a href="#/debug">Owner diagnostics</a></p>
    ${!state.data.projects.length ? '<p>No projects received. Register a device, configure workspace folders, then run the local collector. The hosted server cannot inspect your Windows folders.</p>' : ''}
    <p>${c.devices.filter(d=>d.status==='online').length} active devices · ${c.activity.filter(e=>e.event_type==='commit' && Date.now()-Date.parse(e.timestamp)<7*86400000).length} observed commits in 7 days</p>
    ${c.devices.map(d=>`<p><b>${esc(d.device_name || d.id)}</b> · ${esc(d.status.toUpperCase())} · Last heartbeat: ${d.last_seen ? esc(ago(d.last_seen)) : 'never'} · ${d.projects_synced || 0} projects<br>Last connection attempt: ${d.last_attempt ? esc(ago(d.last_attempt)) : 'Never'} · Last successful sync: ${d.last_sync ? esc(ago(d.last_sync)) : 'Never'}<br>Last error: ${esc(d.last_error || 'None reported by server')}</p>`).join('') || '<p>No collectors registered.</p>'}
    ${c.devices.map(d=>`<p class="muted">${esc(d.device_name || d.id)} · Agent ${esc(d.agent_version || 'not yet enrolled')} · ${d.queue_size || 0} events pending on last heartbeat</p>`).join('')}
    <p class="muted">GitHub and Render integrations not configured. AI adapters are disabled in the agent MVP. File modifications are Git observations; no editor monitoring is enabled.</p>
    ${['claude','codex'].map(name=>`<p>${esc(name)}: ${c.sources.some(s=>s.name===name&&s.status==='connected') ? c.activity.some(e=>e.source===name) ? 'Local session metadata detected' : 'Connected · No activity detected in recognized workspaces' : 'Unavailable or not yet synced'}</p>`).join('')}
    <button class="btn" data-act="centralSync">Sync now</button><p id="centralSyncStatus" role="status"></p>
    ${c.sync_requests.map(r=>`<p>${esc(r.device_id)}: ${r.fulfilled_at && r.fulfilled_at>=r.requested_at ? 'Sync complete' : 'Syncing… awaiting collector heartbeat'}${c.devices.find(d=>d.id===r.device_id)?.status==='offline' ? ' · Device offline; previous data retained' : ''}</p>`).join('')}
  </section>`;
}

export function integrationsView() {
  const c = state.data.central;
  return `<h1>Settings → Integrations</h1><a href="#/">Dashboard</a>${sourcePanel()}
    <section class="card" style="padding:20px"><h2>Connect a computer</h2>
    <p>On that Windows computer, run <code>powershell -NoProfile -ExecutionPolicy Bypass -File .\\setup_collector.ps1</code> from the repository folder. It suggests workspaces, pairs this computer, proves heartbeat, then verifies one Git repository before syncing more.</p>
    <h3>Approve a pairing code</h3><p>Approve only the exact code displayed by setup on your own computer. Credentials are generated locally, protected with Windows DPAPI, and are separate from your browser password.</p>
    <p>After pairing and folder confirmation, run <code>powershell -NoProfile -ExecutionPolicy Bypass -File .\\install_agent.ps1</code> once to start Project Dashboard Agent automatically at Windows sign-in.</p>
    <form data-act="approveCollectorPair"><label>Pairing code <input name="code" required pattern="[A-Za-z0-9]{12}" maxlength="12"></label><button class="btn" type="submit">Approve this computer</button></form>
    ${(c.pairings || []).map(p=>`<p>Pending: ${esc(p.device_name)} · ${esc(p.platform)} · code <b>${esc(p.code)}</b> · expires ${esc(p.expires_at)}</p>`).join('')}
    <h3>Manual collector token</h3>
    <p>Register each computer separately. The token appears once; set it as COLLECTOR_TOKEN on that computer. Registering an existing ID rotates its token.</p>
    <form data-act="registerCollector"><label>Device ID <input name="device" required pattern="[A-Za-z0-9_.-]{1,80}" placeholder="YousseF-Desktop"></label><button class="btn" type="submit">Generate collector token</button></form>
    <div id="collectorCredential" role="status"></div>
    <p>Copy collector.config.example.json to collector.config.json, set your workspace folders, then run <code>python collector.py --once</code> to test or <code>python collector.py</code> to sync periodically.</p>
    </section><section class="card" style="padding:20px;margin-top:20px"><h2>Transfer saved dashboard data</h2>
    <p>Bring saved projects, tasks, analyses, daily plans and physical builds from your local dashboard. Existing collector credentials and owner edits are preserved. This does not scan folders or read AI chat storage.</p>
    <button class="btn" data-act="exportDashboard">Download dashboard export</button>
    <form data-act="importDashboard"><label>Dashboard export <input type="file" name="bundle" accept=".json,application/json" required></label><button class="btn" type="submit">Import saved dashboard</button></form>
    <p id="dashboardTransferStatus" role="status"></p>
    </section><section class="card" style="padding:20px;margin-top:20px"><h2>Source health</h2>
    ${c.sources.map(s=>`<p><b>${esc(s.device_id)} / ${esc(s.name)}</b> · ${esc(s.status)} · Last success: ${s.last_success ? esc(ago(s.last_success)) : 'never'} · ${s.projects} projects<br>${esc([...s.errors,...s.warnings].join('; '))}</p>`).join('') || '<p>No source reports received.</p>'}
    ${c.devices.map(d=>`<p>${esc(d.id)} <button class="btn" data-act="revokeCollector" data-device="${esc(d.id)}">Revoke token</button></p>`).join('')}</section>`;
}

export function instructionForm() {
  return `<section class="card" style="padding:20px;margin-bottom:20px"><h2>Your instructions come first</h2>
    <form data-act="humanInstruction"><label>Project <select name="project" required>${state.data.projects.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select></label>
    <label>Standing instruction <textarea name="text" rows="2" maxlength="2000" required placeholder="What should this project focus on?"></textarea></label><button class="btn" type="submit" ${state.data.projects.length?'':'disabled'}>Save instruction and update priorities</button></form>
    <p class="muted">Saved literally as a high-priority human task and standing focus instruction. Recommendations use the existing explainable rules engine.</p>
    ${(state.data.planner?.directives || []).map(d=>`<p>${esc(d.project_name || '')} · ${esc(d.text || d.summary)} <button class="btn" data-act="planEndDirective" data-id="${d.id}">End instruction</button></p>`).join('')}</section>`;
}

export function debugView() {
  const c = state.data.central;
  return `<h1>Owner diagnostics</h1><p><a href="#/">Dashboard</a> · <a href="/api/debug" target="_blank">Server/database diagnostic JSON</a></p>
    ${sourcePanel()}<section class="card" style="padding:20px"><h2>Latest ingestion attempts</h2>
    ${c.ingestion.map(e=>`<p>${esc(e.timestamp)} · ${esc(e.device_id || 'unauthenticated')} · <b>${esc(e.status)}</b> · ${esc(e.reason)} · ${e.projects} projects</p>`).join('') || '<p>No ingestion attempts. If data is missing, check collector URL, connectivity and COLLECTOR_TOKEN.</p>'}
    <h2>Sync requests</h2>${c.sync_requests.map(r=>`<p>${esc(r.device_id)} · ${r.fulfilled_at && r.fulfilled_at>=r.requested_at ? 'Sync complete' : 'Syncing… waiting for collector'} · requested ${esc(ago(r.requested_at))}</p>`).join('') || '<p>No requests.</p>'}</section>`;
}
