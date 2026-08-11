/* Switchboard Mimic — frontend */

const COLOR_RGB = {
  Red: 'rgb(255,0,0)', Yellow: 'rgb(255,255,0)', Green: 'rgb(0,255,0)',
  Gray: 'rgb(169,169,169)', Blue: 'rgb(0,0,255)',
};

// Registros del simulador (mismo mapa que la pestaña 'Modbus Simulation' original)
const SIM_REGISTERS = [
  { addr: 104, name: 'Incom (104)' },
  { addr: 105, name: 'Breaker Utility: cerrado (105)' },
  { addr: 106, name: 'Breaker Utility: abierto (106)' },
  { addr: 107, name: 'Breaker Utility: disparado (107)' },
  { addr: 110, name: 'Bus A (110)' },
  { addr: 115, name: 'Breaker Feeder: cerrado (115)' },
  { addr: 116, name: 'Breaker Feeder: abierto (116)' },
  { addr: 117, name: 'Breaker Feeder: disparado (117)' },
];

let segments = [];
let selectedId = null;
let types = [];

const $ = (id) => document.getElementById(id);

/* ---------- WebSocket ---------- */

function connectWs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => setBadge('conn-badge', 'en vivo', 'ok');
  ws.onclose = () => {
    setBadge('conn-badge', 'desconectado', 'err');
    setTimeout(connectWs, 2000);
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'state') applyState(msg.data);
  };
}

function setBadge(id, text, cls) {
  const el = $(id);
  el.textContent = text;
  el.className = `badge ${cls || ''}`;
}

function applyState(state) {
  renderStrip(state.pixels);
  if (state.modbus_ok === null) setBadge('modbus-badge', 'Modbus: —');
  else if (state.modbus_ok) setBadge('modbus-badge', 'Modbus: OK', 'ok');
  else setBadge('modbus-badge', 'Modbus: error', 'err');
  $('test-mode').checked = state.test_mode;
  // colores calculados por el motor
  const colorById = {};
  for (const row of state.segments) colorById[row.id] = row.color;
  document.querySelectorAll('#segments-table tbody tr').forEach((tr) => {
    const chip = tr.querySelector('.chip');
    const color = colorById[Number(tr.dataset.id)];
    if (chip) chip.style.background = COLOR_RGB[color] || 'transparent';
  });
}

/* ---------- tira LED ---------- */

function renderStrip(pixels) {
  const strip = $('strip');
  if (strip.childElementCount !== pixels.length) {
    strip.innerHTML = '';
    pixels.forEach((_, i) => {
      const led = document.createElement('div');
      led.className = 'led';
      led.textContent = i + 1;
      strip.appendChild(led);
    });
  }
  [...strip.children].forEach((led, i) => {
    const [r, g, b] = pixels[i];
    led.style.background = `rgb(${r},${g},${b})`;
    led.style.color = r + g + b > 300 ? '#222' : '#667';
  });
}

/* ---------- tabla ---------- */

async function loadSegments() {
  const res = await fetch('/api/segments');
  const data = await res.json();
  segments = data.segments;
  if (!types.length) {
    types = data.types;
    const sel = $('f-type');
    sel.innerHTML = types.map((t) => `<option>${t}</option>`).join('');
  }
  renderTable();
}

function renderTable() {
  const tbody = document.querySelector('#segments-table tbody');
  tbody.innerHTML = '';
  for (const seg of segments) {
    const tr = document.createElement('tr');
    tr.dataset.id = seg.id;
    if (seg.id === selectedId) tr.classList.add('selected');
    tr.innerHTML = `
      <td>${seg.id}</td><td>${seg.start}</td><td>${seg.end}</td>
      <td>${escapeHtml(seg.description)}</td><td>${seg.type}</td><td>${seg.station}</td>
      <td><span class="chip"></span></td>`;
    tr.onclick = () => selectRow(seg);
    tbody.appendChild(tr);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

async function selectRow(seg) {
  selectedId = seg.id;
  $('f-id').value = seg.id;
  $('f-start').value = seg.start;
  $('f-end').value = seg.end;
  $('f-description').value = seg.description;
  $('f-type').value = seg.type;
  $('f-station').value = seg.station;
  $('btn-update').disabled = false;
  $('btn-delete').disabled = false;
  renderTable();
  await fetch(`/api/select/${seg.id}`, { method: 'POST' });
}

function dismiss() {
  selectedId = null;
  $('f-id').value = '';
  $('btn-update').disabled = true;
  $('btn-delete').disabled = true;
  renderTable();
  fetch('/api/select/0', { method: 'POST' });
}

function formPayload() {
  return {
    start: Number($('f-start').value),
    end: Number($('f-end').value),
    description: $('f-description').value,
    type: $('f-type').value,
    station: Number($('f-station').value),
  };
}

/* ---------- simulador ---------- */

function buildSimPanel() {
  const panel = $('sim-panel');
  for (const reg of SIM_REGISTERS) {
    const row = document.createElement('div');
    row.className = 'sim-row';
    row.innerHTML = `<span class="name">${reg.name}</span>`;
    for (const val of [1, 0]) {
      const btn = document.createElement('button');
      btn.textContent = val ? 'ON (1)' : 'OFF (0)';
      if (val) btn.classList.add('on');
      btn.onclick = async () => {
        await fetch('/api/modbus/write', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ address: reg.addr, value: val }),
        });
        await fetch('/api/refresh', { method: 'POST' });
      };
      row.appendChild(btn);
    }
    panel.appendChild(row);
  }
}

/* ---------- eventos ---------- */

$('segment-form').onsubmit = async (ev) => {
  ev.preventDefault();
  await fetch('/api/segments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formPayload()),
  });
  await loadSegments();
};

$('btn-update').onclick = async () => {
  if (!selectedId) return;
  await fetch(`/api/segments/${selectedId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formPayload()),
  });
  await loadSegments();
};

$('btn-delete').onclick = async () => {
  if (!selectedId) return;
  await fetch(`/api/segments/${selectedId}`, { method: 'DELETE' });
  dismiss();
  await loadSegments();
};

$('btn-dismiss').onclick = dismiss;

$('btn-clear').onclick = async () => {
  if (!confirm('¿Vaciar toda la tabla de segmentos?')) return;
  await fetch('/api/segments', { method: 'DELETE' });
  dismiss();
  await loadSegments();
};

$('btn-refresh').onclick = () => fetch('/api/refresh', { method: 'POST' });

$('test-mode').onchange = (ev) =>
  fetch(`/api/test-mode/${ev.target.checked}`, { method: 'POST' });

/* ---------- init ---------- */

loadSegments();
buildSimPanel();
connectWs();
