"""Root dashboard for HA ingress panel — interactive automation builder."""
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
    background: #1c1c1c; color: #e1e1e1;
  }
  a { color: #64b5f6; text-decoration: none; }
  a:hover { text-decoration: underline; }

  /* ── Header ── */
  .header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 16px 24px; border-bottom: 1px solid #333;
  }
  .header h1 { font-size: 1.3rem; }
  .header .sub { color: #888; font-size: 0.8rem; }

  /* ── Tabs ── */
  .tabs {
    display: flex; gap: 0; border-bottom: 2px solid #333;
    padding: 0 24px; background: #222;
  }
  .tab {
    padding: 12px 20px; cursor: pointer; color: #888;
    border-bottom: 2px solid transparent; margin-bottom: -2px;
    font-size: 0.9rem; transition: all 0.2s;
  }
  .tab:hover { color: #ccc; }
  .tab.active { color: #64b5f6; border-bottom-color: #64b5f6; }

  /* ── Content ── */
  .content { padding: 24px; }
  .tab-content { display: none; }
  .tab-content.active { display: block; }

  /* ── Cards / Grid ── */
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
  .status-line { display: flex; align-items: center; padding: 4px 0; }
  .scenario { padding: 6px 0; border-bottom: 1px solid #333; }
  .scenario:last-child { border-bottom: none; }
  .loading { color: #666; font-style: italic; }

  /* ── Buttons ── */
  .btn {
    padding: 8px 16px; border-radius: 8px; border: none;
    cursor: pointer; font-size: 0.85rem; transition: all 0.2s;
  }
  .btn-primary { background: #1976d2; color: #fff; }
  .btn-primary:hover { background: #1565c0; }
  .btn-secondary { background: #333; color: #ccc; border: 1px solid #444; }
  .btn-secondary:hover { background: #444; }
  .btn-danger { background: #c62828; color: #fff; }
  .btn-danger:hover { background: #b71c1c; }
  .btn-success { background: #2e7d32; color: #fff; }
  .btn-success:hover { background: #1b5e20; }
  .btn-sm { padding: 4px 10px; font-size: 0.8rem; }
  .btn-group { display: flex; gap: 8px; margin-top: 12px; }

  /* ── Rules list ── */
  .rule-item {
    background: #2a2a2a; border: 1px solid #333; border-radius: 10px;
    padding: 16px; margin-bottom: 12px;
  }
  .rule-header { display: flex; justify-content: space-between; align-items: center; }
  .rule-name { font-weight: 600; font-size: 1rem; }
  .rule-meta { color: #888; font-size: 0.8rem; margin-top: 4px; }
  .rule-badge {
    padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600;
  }
  .badge-user { background: #1565c0; color: #fff; }
  .badge-ml { background: #7b1fa2; color: #fff; }
  .badge-approved { background: #2e7d32; color: #fff; }
  .badge-disabled { background: #555; color: #999; }
  .rule-conditions, .rule-actions {
    margin-top: 8px; padding: 8px; background: #222; border-radius: 6px;
    font-size: 0.85rem;
  }
  .rule-conditions label, .rule-actions label {
    color: #888; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px;
  }
  .toggle {
    position: relative; width: 40px; height: 22px; cursor: pointer;
  }
  .toggle input { opacity: 0; width: 0; height: 0; }
  .toggle .slider {
    position: absolute; inset: 0; background: #555; border-radius: 11px;
    transition: 0.3s;
  }
  .toggle .slider:before {
    content: ''; position: absolute; height: 16px; width: 16px;
    left: 3px; bottom: 3px; background: #ccc; border-radius: 50%;
    transition: 0.3s;
  }
  .toggle input:checked + .slider { background: #4caf50; }
  .toggle input:checked + .slider:before { transform: translateX(18px); }

  /* ── Modal ── */
  .modal-overlay {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7);
    z-index: 100; justify-content: center; align-items: center;
  }
  .modal-overlay.open { display: flex; }
  .modal {
    background: #2a2a2a; border-radius: 16px; padding: 24px;
    width: 90%; max-width: 560px; max-height: 80vh; overflow-y: auto;
    border: 1px solid #444;
  }
  .modal h2 { margin-bottom: 16px; font-size: 1.1rem; }
  .form-group { margin-bottom: 14px; }
  .form-group label { display: block; color: #aaa; font-size: 0.8rem; margin-bottom: 4px; }
  .form-group input, .form-group select, .form-group textarea {
    width: 100%; padding: 8px 12px; background: #1c1c1c; border: 1px solid #444;
    border-radius: 8px; color: #e1e1e1; font-size: 0.9rem;
  }
  .form-group textarea { min-height: 60px; resize: vertical; font-family: inherit; }
  .form-group input:focus, .form-group select:focus, .form-group textarea:focus {
    outline: none; border-color: #1976d2;
  }

  /* ── Condition/Action builder ── */
  .builder-row {
    display: flex; gap: 8px; align-items: center; margin-bottom: 8px;
    background: #222; padding: 8px; border-radius: 6px;
  }
  .builder-row select, .builder-row input {
    padding: 6px 8px; background: #1c1c1c; border: 1px solid #444;
    border-radius: 6px; color: #e1e1e1; font-size: 0.85rem;
  }
  .builder-row select { min-width: 120px; }
  .builder-row input { flex: 1; min-width: 80px; }
  .builder-row .remove-btn {
    background: none; border: none; color: #f44336; cursor: pointer;
    font-size: 1.1rem; padding: 4px;
  }
  .add-row-btn {
    background: none; border: 1px dashed #555; color: #888;
    padding: 6px 12px; border-radius: 6px; cursor: pointer;
    font-size: 0.85rem; width: 100%;
  }
  .add-row-btn:hover { border-color: #888; color: #ccc; }

  /* ── ML Suggestions ── */
  .suggestion-item {
    background: linear-gradient(135deg, #2a2a2a, #1a1a2e);
    border: 1px solid #7b1fa2; border-radius: 10px;
    padding: 16px; margin-bottom: 12px;
  }
  .score-bar {
    height: 4px; background: #333; border-radius: 2px; margin-top: 8px;
  }
  .score-fill { height: 100%; background: #7b1fa2; border-radius: 2px; }

  /* ── Patterns heatmap ── */
  .heatmap { display: grid; grid-template-columns: 60px repeat(24, 1fr); gap: 1px; }
  .heatmap-cell {
    aspect-ratio: 1; border-radius: 3px; font-size: 0.6rem;
    display: flex; align-items: center; justify-content: center;
  }
  .heatmap-label { font-size: 0.75rem; color: #888; display: flex; align-items: center; }
  .heatmap-header { font-size: 0.65rem; color: #666; text-align: center; }

  /* ── Empty state ── */
  .empty-state {
    text-align: center; padding: 40px 20px; color: #666;
  }
  .empty-state p { margin-top: 8px; }
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>Hyggebo Brain</h1>
    <div class="sub">Smart home intelligence engine</div>
  </div>
  <span class="sub" id="version"></span>
</div>

<div class="tabs">
  <div class="tab active" data-tab="overview">Oversigt</div>
  <div class="tab" data-tab="rules">Automationer</div>
  <div class="tab" data-tab="ml">ML Forslag</div>
  <div class="tab" data-tab="patterns">Aktivitet</div>
</div>

<div class="content">
  <!-- ══ OVERVIEW TAB ══ -->
  <div id="tab-overview" class="tab-content active">
    <div class="grid">
      <div class="card">
        <h2>Rum</h2>
        <div id="rooms"><span class="loading">Indlaeser...</span></div>
      </div>
      <div class="card">
        <h2>Hus tilstand</h2>
        <div id="state"><span class="loading">Indlaeser...</span></div>
      </div>
      <div class="card">
        <h2>Personer</h2>
        <div id="persons"><span class="loading">Indlaeser...</span></div>
      </div>
      <div class="card">
        <h2>System</h2>
        <div id="health"><span class="loading">Indlaeser...</span></div>
      </div>
      <div class="card">
        <h2>Seneste haendelser</h2>
        <div id="events"><span class="loading">Indlaeser...</span></div>
      </div>
    </div>
  </div>

  <!-- ══ RULES TAB ══ -->
  <div id="tab-rules" class="tab-content">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2 style="font-size:1.1rem">Mine automationer</h2>
      <button class="btn btn-primary" onclick="openNewRule()">+ Ny automation</button>
    </div>
    <div id="rules-list"><span class="loading">Indlaeser...</span></div>
  </div>

  <!-- ══ ML TAB ══ -->
  <div id="tab-ml" class="tab-content">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <div>
        <h2 style="font-size:1.1rem">ML Forslag</h2>
        <p style="color:#888;font-size:0.85rem;margin-top:4px">
          Baseret paa aktivitetsmoenstre foreslaar AI nye automationer
        </p>
      </div>
      <button class="btn btn-secondary" onclick="runAnalysis()">Analyser nu</button>
    </div>
    <div id="ml-list"><span class="loading">Indlaeser...</span></div>
  </div>

  <!-- ══ PATTERNS TAB ══ -->
  <div id="tab-patterns" class="tab-content">
    <h2 style="font-size:1.1rem;margin-bottom:8px">Aktivitetsmoenstre</h2>
    <p style="color:#888;font-size:0.85rem;margin-bottom:16px">
      Belaegning per rum, ugedag og time (laert fra sensordata)
    </p>
    <div class="form-group" style="max-width:240px;margin-bottom:16px">
      <select id="pattern-room" onchange="loadPatterns()">
        <option value="">Vaelg rum...</option>
      </select>
    </div>
    <div id="patterns-view"></div>
  </div>
</div>

<!-- ══ NEW/EDIT RULE MODAL ══ -->
<div class="modal-overlay" id="rule-modal">
  <div class="modal">
    <h2 id="modal-title">Ny automation</h2>
    <input type="hidden" id="edit-rule-id">

    <div class="form-group">
      <label>Navn</label>
      <input type="text" id="rule-name" placeholder="F.eks. Taend lys i koekken om morgenen">
    </div>

    <div class="form-group">
      <label>Beskrivelse</label>
      <textarea id="rule-desc" placeholder="Valgfri beskrivelse..."></textarea>
    </div>

    <div class="form-group">
      <label>Betingelser</label>
      <div id="cond-builder"></div>
      <button class="add-row-btn" onclick="addCondition()">+ Tilfoej betingelse</button>
    </div>

    <div class="form-group">
      <label>Handlinger</label>
      <div id="action-builder"></div>
      <button class="add-row-btn" onclick="addAction()">+ Tilfoej handling</button>
    </div>

    <div class="form-group">
      <label>Cooldown (sekunder)</label>
      <input type="number" id="rule-cooldown" value="300" min="0">
    </div>

    <div class="btn-group">
      <button class="btn btn-primary" onclick="saveRule()">Gem</button>
      <button class="btn btn-secondary" onclick="closeModal()">Annuller</button>
    </div>
  </div>
</div>

<script>
const BASE = window.location.pathname.replace(/\\/$/, '');
const API = BASE + '/api';

const ROOMS = {
  alrum: 'Alrum', koekken: 'Koekken', gang: 'Gang',
  badevaerelse: 'Badevaerelse', udestue: 'Udestue',
  sovevaerelse: 'Sovevaerelse', darwins_vaerelse: 'Darwins Vaerelse'
};
const PERSONS = {
  'person.troels': 'Troels', 'person.hanne': 'Hanne',
  'person.darwin': 'Darwin', 'person.maria': 'Maria'
};
const DAYS_DA = ['Man','Tir','Ons','Tor','Fre','Lor','Son'];

// ── API helper ──
async function api(path, opts) {
  try {
    const r = await fetch(API + path, opts);
    if (!r.ok) { const e = await r.json().catch(()=>({})); throw new Error(e.detail || r.statusText); }
    return await r.json();
  } catch(e) { console.error('API error:', path, e); return null; }
}
async function apiPost(path, body) {
  return api(path, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
}
async function apiPut(path, body) {
  return api(path, { method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
}
async function apiDel(path) {
  return api(path, { method:'DELETE' });
}

// ── Tab navigation ──
document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    document.getElementById('tab-' + t.dataset.tab).classList.add('active');
    if (t.dataset.tab === 'rules') loadRules();
    if (t.dataset.tab === 'ml') loadML();
    if (t.dataset.tab === 'patterns') initPatternRoom();
  });
});

// ── OVERVIEW ──
async function loadOverview() {
  // Rooms
  const rooms = await api('/rooms');
  const re = document.getElementById('rooms');
  if (!rooms) { re.innerHTML = '<span class="clear">Ikke tilgaengelig</span>'; }
  else {
    re.innerHTML = rooms.map(r => {
      const name = ROOMS[r.room_id] || r.room_id;
      const occ = r.occupancy === 'occupied';
      const src = r.source && r.source !== 'none' ? ' (' + r.source + ')' : '';
      return '<div class="room"><span class="room-name">' + name + '</span><span class="' + (occ?'occupied':'clear') + '">' + (occ?'Optaget':'Tom') + src + '</span></div>';
    }).join('');
  }

  // State
  const st = await api('/state');
  const se = document.getElementById('state');
  if (!st) { se.innerHTML = '<span class="clear">Ikke tilgaengelig</span>'; }
  else {
    se.innerHTML = '<div class="room"><span>Hus tilstand</span><span><b>' + st.hus_tilstand + '</b></span></div>'
      + '<div class="room"><span>Tid paa dagen</span><span><b>' + st.tid_pa_dagen + '</b></span></div>';
  }

  // Persons
  const ps = await api('/persons');
  const pe = document.getElementById('persons');
  if (!ps) { pe.innerHTML = '<span class="clear">Ikke tilgaengelig</span>'; }
  else {
    pe.innerHTML = Object.entries(ps).map(([id, state]) => {
      const name = PERSONS[id] || id;
      const home = state === 'home';
      return '<div class="room"><span>' + name + '</span><span class="' + (home?'occupied':'clear') + '">' + (home?'Hjemme':'Ude') + '</span></div>';
    }).join('');
  }

  // Health
  const h = await api('/health');
  const he = document.getElementById('health');
  if (!h) { he.innerHTML = '<span class="clear">Ikke tilgaengelig</span>'; }
  else {
    const lines = Object.entries(h.components).map(([k,v]) => {
      const ok = v==='connected'||v==='running'||v==='active';
      return '<div class="status-line"><span class="status-dot ' + (ok?'ok':'err') + '"></span>' + k + ': ' + v + '</div>';
    });
    lines.unshift('<div class="status-line"><b>v' + h.version + '</b>&nbsp;— ' + h.status + '</div>');
    he.innerHTML = lines.join('');
    document.getElementById('version').textContent = 'v' + h.version;
  }

  // Events
  const ev = await api('/events?limit=5');
  const ee = document.getElementById('events');
  if (!ev || !ev.length) { ee.innerHTML = '<span class="clear">Ingen haendelser endnu</span>'; }
  else {
    ee.innerHTML = ev.map(e => {
      const t = new Date(e.ts).toLocaleTimeString('da-DK');
      return '<div class="scenario"><span>' + e.event_type + '</span><br><small style="color:#666">' + t + ' | ' + e.source + (e.room_id ? ' | ' + (ROOMS[e.room_id]||e.room_id) : '') + '</small></div>';
    }).join('');
  }
}

// ── RULES ──
async function loadRules() {
  const list = document.getElementById('rules-list');
  const rules = await api('/rules');
  if (!rules || !rules.length) {
    list.innerHTML = '<div class="empty-state"><h3>Ingen automationer endnu</h3><p>Opret din foerste automation med knappen ovenfor</p></div>';
    return;
  }
  list.innerHTML = rules.map(r => {
    const badge = r.source === 'ml_approved' ? '<span class="rule-badge badge-approved">ML</span>'
      : r.source === 'ml_suggested' ? '<span class="rule-badge badge-ml">Forslag</span>'
      : '<span class="rule-badge badge-user">Bruger</span>';
    const disabledBadge = !r.enabled ? ' <span class="rule-badge badge-disabled">Deaktiveret</span>' : '';
    const last = r.last_triggered ? new Date(r.last_triggered).toLocaleString('da-DK') : 'aldrig';
    const conds = (r.conditions || []).map(c => conditionText(c)).join(', ') || 'Ingen';
    const acts = (r.actions || []).map(a => actionText(a)).join(', ') || 'Ingen';

    return '<div class="rule-item">'
      + '<div class="rule-header">'
      + '<div><span class="rule-name">' + esc(r.name) + '</span> ' + badge + disabledBadge + '</div>'
      + '<label class="toggle"><input type="checkbox" ' + (r.enabled?'checked':'') + ' onchange="toggleRule(' + r.id + ',this.checked)"><span class="slider"></span></label>'
      + '</div>'
      + (r.description ? '<div class="rule-meta">' + esc(r.description) + '</div>' : '')
      + '<div class="rule-meta">Udloest ' + r.trigger_count + ' gange | Sidst: ' + last + ' | Cooldown: ' + r.cooldown + 's</div>'
      + '<div class="rule-conditions"><label>Betingelser</label><div>' + esc(conds) + '</div></div>'
      + '<div class="rule-actions"><label>Handlinger</label><div>' + esc(acts) + '</div></div>'
      + '<div class="btn-group">'
      + '<button class="btn btn-secondary btn-sm" onclick="editRule(' + r.id + ')">Rediger</button>'
      + '<button class="btn btn-danger btn-sm" onclick="deleteRule(' + r.id + ')">Slet</button>'
      + '</div></div>';
  }).join('');
}

function conditionText(c) {
  if (c.type === 'time') return 'Kl. ' + (c.hour||0) + (c.day_of_week !== undefined ? ' (' + DAYS_DA[c.day_of_week] + ')' : '');
  if (c.type === 'room_occupied') return (ROOMS[c.room_id]||c.room_id) + ' optaget';
  if (c.type === 'room_empty') return (ROOMS[c.room_id]||c.room_id) + ' tom';
  if (c.type === 'person_home') return (PERSONS[c.person_id]||c.person_id) + ' hjemme';
  if (c.type === 'person_away') return (PERSONS[c.person_id]||c.person_id) + ' ude';
  if (c.type === 'state') return 'Tilstand: ' + (c.value||'');
  return JSON.stringify(c);
}

function actionText(a) {
  if (a.type === 'notify') return 'Notifikation: ' + (a.message||'');
  if (a.type === 'ha_service') return 'HA tjeneste: ' + (a.service||'');
  if (a.type === 'mqtt_publish') return 'MQTT: ' + (a.topic||'');
  return JSON.stringify(a);
}

async function toggleRule(id, enabled) {
  await apiPost('/rules/' + id + '/toggle?enabled=' + enabled);
}

async function deleteRule(id) {
  if (!confirm('Slet denne automation?')) return;
  await apiDel('/rules/' + id);
  loadRules();
}

async function editRule(id) {
  const r = await api('/rules/' + id);
  if (!r) return;
  document.getElementById('modal-title').textContent = 'Rediger automation';
  document.getElementById('edit-rule-id').value = r.id;
  document.getElementById('rule-name').value = r.name;
  document.getElementById('rule-desc').value = r.description || '';
  document.getElementById('rule-cooldown').value = r.cooldown;

  // Load conditions
  document.getElementById('cond-builder').innerHTML = '';
  (r.conditions || []).forEach(c => addCondition(c));

  // Load actions
  document.getElementById('action-builder').innerHTML = '';
  (r.actions || []).forEach(a => addAction(a));

  document.getElementById('rule-modal').classList.add('open');
}

function openNewRule() {
  document.getElementById('modal-title').textContent = 'Ny automation';
  document.getElementById('edit-rule-id').value = '';
  document.getElementById('rule-name').value = '';
  document.getElementById('rule-desc').value = '';
  document.getElementById('rule-cooldown').value = 300;
  document.getElementById('cond-builder').innerHTML = '';
  document.getElementById('action-builder').innerHTML = '';
  addCondition();
  addAction();
  document.getElementById('rule-modal').classList.add('open');
}

function closeModal() {
  document.getElementById('rule-modal').classList.remove('open');
}

// ── Condition builder ──
function addCondition(data) {
  const wrap = document.getElementById('cond-builder');
  const row = document.createElement('div');
  row.className = 'builder-row';

  const type = data ? data.type : 'time';
  row.innerHTML = '<select class="cond-type" onchange="updateCondRow(this)">'
    + '<option value="time"' + (type==='time'?' selected':'') + '>Tidspunkt</option>'
    + '<option value="room_occupied"' + (type==='room_occupied'?' selected':'') + '>Rum optaget</option>'
    + '<option value="room_empty"' + (type==='room_empty'?' selected':'') + '>Rum tom</option>'
    + '<option value="person_home"' + (type==='person_home'?' selected':'') + '>Person hjemme</option>'
    + '<option value="person_away"' + (type==='person_away'?' selected':'') + '>Person ude</option>'
    + '<option value="state"' + (type==='state'?' selected':'') + '>Hus tilstand</option>'
    + '</select>'
    + '<div class="cond-params"></div>'
    + '<button class="remove-btn" onclick="this.parentElement.remove()">x</button>';
  wrap.appendChild(row);
  updateCondRow(row.querySelector('.cond-type'), data);
}

function updateCondRow(sel, data) {
  const params = sel.parentElement.querySelector('.cond-params');
  const t = sel.value;
  if (t === 'time') {
    const h = data ? data.hour : 8;
    const d = data && data.day_of_week !== undefined ? data.day_of_week : '';
    params.innerHTML = '<input type="number" class="p-hour" min="0" max="23" value="' + h + '" placeholder="Time (0-23)" style="width:70px">'
      + '<select class="p-dow"><option value="">Alle dage</option>'
      + DAYS_DA.map((n,i) => '<option value="' + i + '"' + (d===i?' selected':'') + '>' + n + '</option>').join('') + '</select>';
  } else if (t === 'room_occupied' || t === 'room_empty') {
    const rid = data ? data.room_id : '';
    params.innerHTML = '<select class="p-room">'
      + Object.entries(ROOMS).map(([k,v]) => '<option value="' + k + '"' + (rid===k?' selected':'') + '>' + v + '</option>').join('') + '</select>';
  } else if (t === 'person_home' || t === 'person_away') {
    const pid = data ? data.person_id : '';
    params.innerHTML = '<select class="p-person">'
      + Object.entries(PERSONS).map(([k,v]) => '<option value="' + k + '"' + (pid===k?' selected':'') + '>' + v + '</option>').join('') + '</select>';
  } else if (t === 'state') {
    const v = data ? data.value : '';
    params.innerHTML = '<select class="p-state">'
      + ['hjemme','nat','ude','kun_hunde','ferie'].map(s => '<option value="' + s + '"' + (v===s?' selected':'') + '>' + s + '</option>').join('') + '</select>';
  }
}

function gatherConditions() {
  const rows = document.querySelectorAll('#cond-builder .builder-row');
  return Array.from(rows).map(row => {
    const t = row.querySelector('.cond-type').value;
    const c = { type: t };
    if (t === 'time') {
      c.hour = parseInt(row.querySelector('.p-hour').value) || 0;
      const d = row.querySelector('.p-dow').value;
      if (d !== '') c.day_of_week = parseInt(d);
    } else if (t === 'room_occupied' || t === 'room_empty') {
      c.room_id = row.querySelector('.p-room').value;
    } else if (t === 'person_home' || t === 'person_away') {
      c.person_id = row.querySelector('.p-person').value;
    } else if (t === 'state') {
      c.value = row.querySelector('.p-state').value;
    }
    return c;
  });
}

// ── Action builder ──
function addAction(data) {
  const wrap = document.getElementById('action-builder');
  const row = document.createElement('div');
  row.className = 'builder-row';

  const type = data ? data.type : 'notify';
  row.innerHTML = '<select class="act-type" onchange="updateActRow(this)">'
    + '<option value="notify"' + (type==='notify'?' selected':'') + '>Notifikation</option>'
    + '<option value="ha_service"' + (type==='ha_service'?' selected':'') + '>HA tjeneste</option>'
    + '<option value="mqtt_publish"' + (type==='mqtt_publish'?' selected':'') + '>MQTT besked</option>'
    + '</select>'
    + '<div class="act-params"></div>'
    + '<button class="remove-btn" onclick="this.parentElement.remove()">x</button>';
  wrap.appendChild(row);
  updateActRow(row.querySelector('.act-type'), data);
}

function updateActRow(sel, data) {
  const params = sel.parentElement.querySelector('.act-params');
  const t = sel.value;
  if (t === 'notify') {
    const m = data ? data.message : '';
    params.innerHTML = '<input type="text" class="p-message" value="' + esc(m) + '" placeholder="Besked...">';
  } else if (t === 'ha_service') {
    const s = data ? data.service : '';
    const d = data ? JSON.stringify(data.data||{}) : '{}';
    params.innerHTML = '<input type="text" class="p-service" value="' + esc(s) + '" placeholder="domain.service" style="width:140px">'
      + '<input type="text" class="p-sdata" value="" placeholder="data JSON">';
    params.querySelector('.p-sdata').value = d;
  } else if (t === 'mqtt_publish') {
    const tp = data ? data.topic : '';
    const pl = data ? data.payload : '';
    params.innerHTML = '<input type="text" class="p-topic" value="' + esc(tp) + '" placeholder="topic" style="width:140px">'
      + '<input type="text" class="p-payload" value="' + esc(pl) + '" placeholder="payload">';
  }
}

function gatherActions() {
  const rows = document.querySelectorAll('#action-builder .builder-row');
  return Array.from(rows).map(row => {
    const t = row.querySelector('.act-type').value;
    const a = { type: t };
    if (t === 'notify') {
      a.message = row.querySelector('.p-message').value;
    } else if (t === 'ha_service') {
      a.service = row.querySelector('.p-service').value;
      try { a.data = JSON.parse(row.querySelector('.p-sdata').value); } catch { a.data = {}; }
    } else if (t === 'mqtt_publish') {
      a.topic = row.querySelector('.p-topic').value;
      a.payload = row.querySelector('.p-payload').value;
    }
    return a;
  });
}

async function saveRule() {
  const id = document.getElementById('edit-rule-id').value;
  const body = {
    name: document.getElementById('rule-name').value.trim(),
    description: document.getElementById('rule-desc').value.trim(),
    conditions: gatherConditions(),
    actions: gatherActions(),
    cooldown: parseInt(document.getElementById('rule-cooldown').value) || 300,
    enabled: true,
  };
  if (!body.name) { alert('Angiv et navn'); return; }

  if (id) {
    await apiPut('/rules/' + id, body);
  } else {
    await apiPost('/rules', body);
  }
  closeModal();
  loadRules();
}

// ── ML SUGGESTIONS ──
async function loadML() {
  const list = document.getElementById('ml-list');
  const data = await api('/ml/suggestions');
  if (!data || !data.length) {
    list.innerHTML = '<div class="empty-state"><h3>Ingen forslag endnu</h3><p>Klik "Analyser nu" naar der er nok sensordata (mindst 1 uge)</p></div>';
    return;
  }
  list.innerHTML = data.map(r => {
    const score = (r.ml_score * 100).toFixed(0);
    return '<div class="suggestion-item">'
      + '<div class="rule-header"><span class="rule-name">' + esc(r.name) + '</span><span class="rule-badge badge-ml">' + score + '% sikker</span></div>'
      + '<div class="rule-meta">' + esc(r.description) + '</div>'
      + '<div class="score-bar"><div class="score-fill" style="width:' + score + '%"></div></div>'
      + '<div class="btn-group">'
      + '<button class="btn btn-success btn-sm" onclick="approveSuggestion(' + r.id + ')">Godkend</button>'
      + '<button class="btn btn-secondary btn-sm" onclick="editRule(' + r.id + ')">Tilpas</button>'
      + '<button class="btn btn-danger btn-sm" onclick="deleteRule(' + r.id + ')">Afvis</button>'
      + '</div></div>';
  }).join('');
}

async function approveSuggestion(id) {
  await apiPost('/ml/suggestions/' + id + '/approve');
  loadML();
}

async function runAnalysis() {
  const btn = event.target;
  btn.textContent = 'Analyserer...';
  btn.disabled = true;
  const res = await apiPost('/ml/analyze');
  btn.textContent = 'Analyser nu';
  btn.disabled = false;
  if (res) alert('Analyse faerdig: ' + res.suggestions_created + ' nye forslag');
  loadML();
}

// ── PATTERNS ──
function initPatternRoom() {
  const sel = document.getElementById('pattern-room');
  if (sel.options.length <= 1) {
    Object.entries(ROOMS).forEach(([k,v]) => {
      const o = document.createElement('option');
      o.value = k; o.textContent = v;
      sel.appendChild(o);
    });
  }
}

async function loadPatterns() {
  const room = document.getElementById('pattern-room').value;
  const view = document.getElementById('patterns-view');
  if (!room) { view.innerHTML = ''; return; }

  const data = await api('/patterns/' + room);
  if (!data || !data.length) {
    view.innerHTML = '<div class="empty-state"><p>Ingen data endnu for dette rum</p></div>';
    return;
  }

  // Build heatmap grid: rows = days, cols = hours
  const grid = Array.from({length:7}, () => Array(24).fill(0));
  data.forEach(p => {
    if (p.day_of_week >= 0 && p.day_of_week < 7 && p.hour >= 0 && p.hour < 24) {
      grid[p.day_of_week][p.hour] = p.occupancy_pct;
    }
  });

  let html = '<div class="heatmap">';
  // Header row
  html += '<div class="heatmap-label"></div>';
  for (let h = 0; h < 24; h++) html += '<div class="heatmap-header">' + h + '</div>';

  // Data rows
  for (let d = 0; d < 7; d++) {
    html += '<div class="heatmap-label">' + DAYS_DA[d] + '</div>';
    for (let h = 0; h < 24; h++) {
      const v = grid[d][h];
      const intensity = Math.min(v / 100, 1);
      const r = Math.round(30 + intensity * 46);
      const g = Math.round(30 + intensity * 125);
      const b = Math.round(30 + intensity * 50);
      const color = 'rgb(' + r + ',' + g + ',' + b + ')';
      html += '<div class="heatmap-cell" style="background:' + color + '" title="' + DAYS_DA[d] + ' kl.' + h + ': ' + v.toFixed(0) + '%">'
        + (v > 0 ? v.toFixed(0) : '') + '</div>';
    }
  }
  html += '</div>';
  view.innerHTML = html;
}

// ── Utils ──
function esc(s) { const d = document.createElement('div'); d.textContent = s||''; return d.innerHTML; }

// ── Init ──
loadOverview();
setInterval(loadOverview, 15000);
</script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the Brain dashboard for HA ingress."""
    return DASHBOARD_HTML
