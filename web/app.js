/* Switchboard Mimic — vista Mímico */

const COLOR_RGB = {
  Red: 'rgb(255,0,0)', Yellow: 'rgb(255,255,0)', Green: 'rgb(0,255,0)',
  Gray: 'rgb(169,169,169)', Blue: 'rgb(0,0,255)',
};

let segments = [];
let elements = [];
let selectedId = null;
let testMode = false;
let activeStrip = 1;
let stripCount = 1;

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
  testMode = state.test_mode;
  stripCount = state.strips.length;
  $('strips').classList.toggle('testing', testMode);
  $('test-hint').hidden = !testMode;
  renderTabs();
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

/* ---------- tira LED ---------- */

function renderTabs() {
  const bar = $('strip-tabs');
  if (bar.childElementCount === stripCount || stripCount < 2) {
    if (stripCount < 2) bar.innerHTML = '';
    return;
  }
  bar.innerHTML = '';
  for (let n = 1; n <= stripCount; n++) {
    const btn = document.createElement('button');
    btn.textContent = `Tira ${n}`;
    btn.classList.toggle('active', n === activeStrip);
    btn.onclick = () => switchStrip(n);
    bar.appendChild(btn);
  }
}

function switchStrip(n) {
  if (n === activeStrip) return;
  activeStrip = n;
  [...$('strip-tabs').children].forEach((btn, i) =>
    btn.classList.toggle('active', i + 1 === n));
  [...$('strips').children].forEach((block, i) => {
    block.style.display = i + 1 === n ? '' : 'none';
  });
  dismiss(); // la selección pertenecía a la otra tira
}

function renderStrips(strips) {
  const container = $('strips');
  // reconstruir si cambió el nº de tiras o el nº de LEDs de alguna
  const stale =
    container.childElementCount !== strips.length ||
    strips.some((s, idx) => {
      const row = container.children[idx].querySelector('.strip');
      return row.childElementCount !== s.pixels.length;
    });
  if (stale) {
    container.innerHTML = '';
    strips.forEach((s, idx) => {
      const block = document.createElement('div');
      block.className = 'strip-block';
      const row = document.createElement('div');
      row.className = 'strip';
      s.pixels.forEach((_, i) => {
        const led = document.createElement('div');
        led.className = 'led';
        led.textContent = i + 1;
        led.onclick = async () => {
          if (!testMode) return;
          await fetch(`/api/test-led/${idx + 1}/${i + 1}`, { method: 'POST' });
        };
        row.appendChild(led);
      });
      block.appendChild(row);
      container.appendChild(block);
    });
  }
  strips.forEach((s, idx) => {
    const block = container.children[idx];
    block.style.display = idx + 1 === activeStrip ? '' : 'none';
    const row = block.querySelector('.strip');
    [...row.children].forEach((led, i) => {
      const [r, g, b] = s.pixels[i];
      led.style.background = `rgb(${r},${g},${b})`;
      led.style.color = r + g + b > 300 ? '#222' : '#667';
      const virtual = i >= s.hw_led_count;
      led.classList.toggle('virtual', virtual);
      led.title = virtual
        ? `LED ${i + 1} — fuera de la tira física configurada (${s.hw_led_count})`
        : `LED ${i + 1}`;
    });
  });
}

/* ---------- tabla ---------- */

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
    if (seg.strip !== activeStrip) continue; // cada tab muestra su tira
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
    strip: activeStrip,
    start: Number($('f-start').value),
    end: Number($('f-end').value),
    element_id: Number($('f-element').value),
  };
}

/* ---------- eventos ---------- */

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
  if (!confirm('¿Vaciar toda la tabla de segmentos (todas las tiras)?')) return;
  await fetch('/api/segments', { method: 'DELETE' });
  dismiss();
  await loadSegments();
};

$('btn-refresh').onclick = () => fetch('/api/refresh', { method: 'POST' });

$('test-mode').onchange = (ev) =>
  fetch(`/api/test-mode/${ev.target.checked}`, { method: 'POST' });

/* ---------- init ---------- */

loadSegments();
connectWs();
