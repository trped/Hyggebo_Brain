"""Root dashboard for HA ingress panel."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="da">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hyggebo Brain</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #1c1c1c; color: #e1e1e1; padding: 24px;
  }
  h1 { font-size: 1.5rem; margin-bottom: 8px; }
  .subtitle { color: #888; margin-bottom: 24px; font-size: 0.9rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
  .card {
    background: #2a2a2a; border-radius: 12px; padding: 20px;
    border: 1px solid #333;
  }
  .card h2 { font-size: 1rem; color: #aaa; margin-bottom: 12px; }
  .room { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #333; }
  .room:last-child { border-bottom: none; }
  .room-name { font-weight: 500; }
  .occupied { color: #4caf50; }
  .clear { color: #666; }
  .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
  .status-dot.ok { background: #4caf50; }
  .status-dot.err { background: #f44336; }
  .status-dot.warn { background: #ff9800; }
  .status-line { display: flex; align-items: center; padding: 4px 0; }
  .scenario { padding: 6px 0; border-bottom: 1px solid #333; }
  .scenario:last-child { border-bottom: none; }
  .loading { color: #666; font-style: italic; }
  a { color: #64b5f6; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .refresh-btn {
    background: #333; border: 1px solid #444; color: #ccc;
    padding: 6px 16px; border-radius: 6px; cursor: pointer; font-size: 0.85rem;
  }
  .refresh-btn:hover { background: #444; }
  .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
  .version { color: #555; font-size: 0.8rem; }
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>Hyggebo Brain</h1>
    <div class="subtitle">Smart home intelligence engine</div>
  </div>
  <button class="refresh-btn" onclick="loadAll()">Opdater</button>
</div>

<div class="grid">
  <div class="card">
    <h2>Rum belægning</h2>
    <div id="rooms"><span class="loading">Indlæser...</span></div>
  </div>

  <div class="card">
    <h2>Hus tilstand</h2>
    <div id="state"><span class="loading">Indlæser...</span></div>
  </div>

  <div class="card">
    <h2>Personstatus</h2>
    <div id="persons"><span class="loading">Indlæser...</span></div>
  </div>

  <div class="card">
    <h2>System</h2>
    <div id="health"><span class="loading">Indlæser...</span></div>
  </div>

  <div class="card">
    <h2>Scenarier</h2>
    <div id="scenarios"><span class="loading">Indlæser...</span></div>
  </div>

  <div class="card">
    <h2>Seneste hændelser</h2>
    <div id="events"><span class="loading">Indlæser...</span></div>
  </div>
</div>

<script>
const BASE = window.location.pathname.replace(/\\/$/, '');
const API = BASE + '/api';

const ROOM_NAMES = {
  alrum: 'Alrum', koekken: 'Køkken', gang: 'Gang',
  badevaerelse: 'Badeværelse', udestue: 'Udestue',
  sovevaerelse: 'Soveværelse', darwins_vaerelse: 'Darwins Værelse'
};

const PERSON_NAMES = {
  'person.troels': 'Troels', 'person.hanne': 'Hanne',
  'person.darwin': 'Darwin', 'person.maria': 'Maria'
};

async function api(path) {
  try {
    const r = await fetch(API + path);
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}

async function loadRooms() {
  const data = await api('/rooms');
  const el = document.getElementById('rooms');
  if (!data) { el.innerHTML = '<span class="clear">Ikke tilgængelig</span>'; return; }
  el.innerHTML = data.map(r => {
    const name = ROOM_NAMES[r.room_id] || r.room_id;
    const occ = r.occupancy === 'occupied';
    const cls = occ ? 'occupied' : 'clear';
    const src = r.source && r.source !== 'none' ? ` (${r.source})` : '';
    return `<div class="room"><span class="room-name">${name}</span><span class="${cls}">${occ ? 'Optaget' : 'Tom'}${src}</span></div>`;
  }).join('');
}

async function loadState() {
  const data = await api('/state');
  const el = document.getElementById('state');
  if (!data) { el.innerHTML = '<span class="clear">Ikke tilgængelig</span>'; return; }
  el.innerHTML = `
    <div class="room"><span>Hus tilstand</span><span><b>${data.hus_tilstand}</b></span></div>
    <div class="room"><span>Tid på dagen</span><span><b>${data.tid_pa_dagen}</b></span></div>
  `;
}

async function loadPersons() {
  const data = await api('/persons');
  const el = document.getElementById('persons');
  if (!data) { el.innerHTML = '<span class="clear">Ikke tilgængelig</span>'; return; }
  el.innerHTML = Object.entries(data).map(([id, state]) => {
    const name = PERSON_NAMES[id] || id;
    const home = state === 'home';
    return `<div class="room"><span>${name}</span><span class="${home ? 'occupied' : 'clear'}">${home ? 'Hjemme' : 'Ude'}</span></div>`;
  }).join('');
}

async function loadHealth() {
  const data = await api('/health');
  const el = document.getElementById('health');
  if (!data) { el.innerHTML = '<span class="clear">Ikke tilgængelig</span>'; return; }
  const lines = Object.entries(data.components).map(([k, v]) => {
    const ok = v === 'connected' || v === 'running' || v === 'active';
    const cls = ok ? 'ok' : 'err';
    return `<div class="status-line"><span class="status-dot ${cls}"></span>${k}: ${v}</div>`;
  });
  lines.unshift(`<div class="status-line"><b>v${data.version}</b>&nbsp;— ${data.status}</div>`);
  el.innerHTML = lines.join('');
}

async function loadScenarios() {
  const data = await api('/scenarios');
  const el = document.getElementById('scenarios');
  if (!data) { el.innerHTML = '<span class="clear">Ikke tilgængelig</span>'; return; }
  el.innerHTML = data.map(r => {
    const last = r.last_triggered ? new Date(r.last_triggered * 1000).toLocaleTimeString('da-DK') : 'aldrig';
    const enabled = r.enabled !== false;
    return `<div class="scenario"><span>${r.name}</span><br><small style="color:#666">Sidst: ${last} | ${enabled ? 'Aktiv' : 'Deaktiveret'}</small></div>`;
  }).join('');
}

async function loadEvents() {
  const data = await api('/events?limit=5');
  const el = document.getElementById('events');
  if (!data || !data.length) { el.innerHTML = '<span class="clear">Ingen hændelser endnu</span>'; return; }
  el.innerHTML = data.map(e => {
    const t = new Date(e.ts).toLocaleTimeString('da-DK');
    return `<div class="scenario"><span>${e.event_type}</span><br><small style="color:#666">${t} | ${e.source}${e.room_id ? ' | ' + (ROOM_NAMES[e.room_id] || e.room_id) : ''}</small></div>`;
  }).join('');
}

function loadAll() {
  loadRooms(); loadState(); loadPersons();
  loadHealth(); loadScenarios(); loadEvents();
}

loadAll();
setInterval(loadAll, 15000);
</script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the Brain dashboard for HA ingress."""
    return DASHBOARD_HTML
