/* Switchboard Mimic — Mimic view */

const COLOR_RGB = {
  Red: 'rgb(255,0,0)', Yellow: 'rgb(255,255,0)', Green: 'rgb(0,255,0)',
  Gray: 'rgb(169,169,169)', Blue: 'rgb(0,0,255)',
};

let segments = [];
let elements = [];
let selectedId = null;
let testMode = false;
let activeStrip = null;   // id of the active strip
let stripsMeta = [];      // [{id, name}] from the last update

const $ = (id) => document.getElementById(id);

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function elementById(id) {
  return elements.find((e) => e.id === id);
}

/* ---------- WebSocket ---------- */

function connectWs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => setBadge('conn-badge', 'live', 'ok');
  ws.onclose = () => {
    setBadge('conn-badge', 'disconnected', 'err');
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
  testMode = state.test_mode;
  const meta = state.strips.map((s) => ({ id: s.id, name: s.name }));
  if (activeStrip === null || !meta.some((m) => m.id === activeStrip)) {
    activeStrip = meta.length ? meta[0].id : null;
  }
  if (JSON.stringify(meta) !== JSON.stringify(stripsMeta)) {
    stripsMeta = meta;
    renderTabs();
    renderTable();
  }
  $('strips').classList.toggle('testing', testMode);
  $('test-hint').hidden = !testMode;
  renderStrips(state.strips);
  if (state.modbus_ok === null) setBadge('modbus-badge', 'Modbus: —');
  else if (state.modbus_ok) setBadge('modbus-badge', 'Modbus: OK', 'ok');
  else setBadge('modbus-badge', 'Modbus: error', 'err');
  $('test-mode').checked = state.test_mode;
  const colorById = {};
  for (const row of state.segments) colorById[row.id] = row.color;
  document.querySelectorAll('#segments-table tbody tr').forEach((tr) => {
    const chip = tr.querySelector('.chip');
    const color = colorById[Number(tr.dataset.id)];
    if (chip) chip.style.background = COLOR_RGB[color] || 'transparent';
  });
}

/* ---------- LED strips ---------- */

function renderTabs() {
  const bar = $('strip-tabs');
  bar.innerHTML = '';
  if (stripsMeta.length < 2) return;
  for (const m of stripsMeta) {
    const btn = document.createElement('button');
    btn.textContent = m.name;
    btn.classList.toggle('active', m.id === activeStrip);
    btn.onclick = () => switchStrip(m.id);
    bar.appendChild(btn);
  }
}

function switchStrip(id) {
  if (id === activeStrip) return;
  activeStrip = id;
  [...$('strip-tabs').children].forEach((btn, i) =>
    btn.classList.toggle('active', stripsMeta[i].id === id));
  [...$('strips').children].forEach((block) => {
    block.style.display = Number(block.dataset.stripId) === id ? '' : 'none';
  });
  dismiss(); // the selection belonged to the other strip
}

function renderStrips(strips) {
  const container = $('strips');
  // rebuild if the strips changed (count, ids) or any LED count changed
  const stale =
    container.childElementCount !== strips.length ||
    strips.some((s, idx) => {
      const block = container.children[idx];
      return (
        Number(block.dataset.stripId) !== s.id ||
        block.querySelector('.strip').childElementCount !== s.pixels.length
      );
    });
  if (stale) {
    container.innerHTML = '';
    for (const s of strips) {
      const block = document.createElement('div');
      block.className = 'strip-block';
      block.dataset.stripId = s.id;
      const row = document.createElement('div');
      row.className = 'strip';
      s.pixels.forEach((_, i) => {
        const led = document.createElement('div');
        led.className = 'led';
        led.textContent = i + 1;
        led.onclick = async () => {
          if (!testMode) return;
          await fetch(`/api/test-led/${s.id}/${i + 1}`, { method: 'POST' });
        };
        row.appendChild(led);
      });
      block.appendChild(row);
      container.appendChild(block);
    }
  }
  strips.forEach((s, idx) => {
    const block = container.children[idx];
    block.style.display = s.id === activeStrip ? '' : 'none';
    const row = block.querySelector('.strip');
    [...row.children].forEach((led, i) => {
      const [r, g, b] = s.pixels[i];
      led.style.background = `rgb(${r},${g},${b})`;
      led.style.color = r + g + b > 300 ? '#222' : '#667';
      const virtual = i >= s.hw_led_count;
      led.classList.toggle('virtual', virtual);
      led.title = virtual
        ? `LED ${i + 1} — beyond the configured physical strip (${s.hw_led_count})`
        : `LED ${i + 1}`;
    });
  });
}

/* ---------- table ---------- */

async function loadSegments() {
  const res = await fetch('/api/segments');
  const data = await res.json();
  segments = data.segments;
  elements = data.elements;

  const sel = $('f-element');
  const current = sel.value;
  sel.innerHTML = elements
    .map((e) => `<option value="${e.id}">${escapeHtml(e.name)}</option>`)
    .join('');
  if (elements.some((e) => String(e.id) === current)) sel.value = current;

  renderTable();
}

function renderTable() {
  const tbody = document.querySelector('#segments-table tbody');
  tbody.innerHTML = '';
  for (const seg of segments) {
    if (seg.strip !== activeStrip) continue; // each tab shows its own strip
    const elem = elementById(seg.element_id);
    const tr = document.createElement('tr');
    tr.dataset.id = seg.id;
    if (seg.id === selectedId) tr.classList.add('selected');
    tr.innerHTML = `
      <td>${seg.id}</td><td>${seg.start}</td><td>${seg.end}</td>
      <td>${elem ? escapeHtml(elem.name) : '—'}</td>
      <td>${elem ? escapeHtml(elem.type) : '—'}</td>
      <td><span class="chip"></span></td>`;
    tr.onclick = () => selectRow(seg);
    tbody.appendChild(tr);
  }
}

async function selectRow(seg) {
  selectedId = seg.id;
  $('f-id').value = seg.id;
  $('f-start').value = seg.start;
  $('f-end').value = seg.end;
  $('f-element').value = seg.element_id;
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
    strip: activeStrip ?? 1,
    start: Number($('f-start').value),
    end: Number($('f-end').value),
    element_id: Number($('f-element').value),
  };
}

/* ---------- events ---------- */

$('segment-form').onsubmit = async (ev) => {
  ev.preventDefault();
  const res = await fetch('/api/segments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formPayload()),
  });
  if (!res.ok) alert((await res.json()).detail);
  await loadSegments();
};

$('btn-update').onclick = async () => {
  if (!selectedId) return;
  const res = await fetch(`/api/segments/${selectedId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formPayload()),
  });
  if (!res.ok) alert((await res.json()).detail);
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
  const name = stripsMeta.find((m) => m.id === activeStrip)?.name ?? activeStrip;
  if (!confirm(`Clear the table for strip "${name}"?`)) return;
  await fetch(`/api/segments?strip=${activeStrip}`, { method: 'DELETE' });
  dismiss();
  await loadSegments();
};

$('btn-refresh').onclick = () => fetch('/api/refresh', { method: 'POST' });

$('test-mode').onchange = (ev) =>
  fetch(`/api/test-mode/${ev.target.checked}`, { method: 'POST' });

/* ---------- init ---------- */

loadSegments();
connectWs();
