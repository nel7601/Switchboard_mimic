/* Switchboard Mimic — Settings page: LED strips, object types, PLC simulator */

const RULE_INFO = {
  simple: 'Modbus read: register[0]=1 → Red, otherwise → Green.',
  breaker: 'Modbus read: register[2]=1 → Yellow (tripped), register[1]=1 → Red, register[0]=1 → Green, otherwise → Gray.',
  bus: 'Like "simple", and also marks this element as the reference Bus for derived types.',
  derived: 'No Modbus read: Red if the reference Bus is Red and the upstream element (the segment ending right before) is Red; otherwise → Green.',
};

// Offsets over the element's base address, by rule
const SIM_OFFSETS = {
  breaker: [
    { off: 0, label: 'closed' },
    { off: 1, label: 'open' },
    { off: 2, label: 'tripped' },
  ],
  simple: [{ off: 0, label: 'state' }],
  bus: [{ off: 0, label: 'state' }],
};

let types = [];
let rules = [];
let elements = [];
let strips = [];

const $ = (id) => document.getElementById(id);

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/* ---------- load ---------- */

async function loadAll() {
  const [tRes, eRes, sRes] = await Promise.all([
    fetch('/api/types'), fetch('/api/elements'), fetch('/api/strips'),
  ]);
  const tData = await tRes.json();
  types = tData.types;
  rules = tData.rules;
  elements = (await eRes.json()).elements;
  strips = (await sRes.json()).strips;
  renderStrips();

  const sel = $('t-rule');
  if (!sel.options.length) {
    sel.innerHTML = rules.map((r) => `<option>${r}</option>`).join('');
    sel.onchange = () => { $('rule-help').textContent = RULE_INFO[sel.value] || ''; };
    sel.onchange();
  }
  renderTypes();
  buildSimPanel();
}

/* ---------- LED strips ---------- */

function renderStrips() {
  const tbody = document.querySelector('#strips-table tbody');
  tbody.innerHTML = '';
  for (const s of strips) {
    const isPwm = s.kind === 'pwm';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${escapeHtml(s.name)}</td>
      <td><code>${isPwm ? 'local PWM' : 'WLED'}</code></td>
      <td>${isPwm ? `GPIO${s.gpio} (PWM${s.channel})` : escapeHtml(`${s.host}:${s.port}`)}</td>
      <td>${s.count}</td>
      <td>${s.used_by}</td>
      <td class="row-actions"></td>`;
    if (!isPwm) {
      const del = document.createElement('button');
      del.textContent = 'Delete';
      del.className = 'danger small';
      del.disabled = s.used_by > 0;
      del.title = s.used_by > 0 ? 'Has assigned segments: cannot delete' : '';
      del.onclick = async (ev) => {
        ev.stopPropagation();
        if (!confirm(`Delete strip "${s.name}"?`)) return;
        const res = await fetch(`/api/strips/${s.id}`, { method: 'DELETE' });
        if (!res.ok) alert((await res.json()).detail);
        await loadAll();
      };
      tr.querySelector('.row-actions').appendChild(del);
    }
    tr.onclick = () => selectStrip(s);
    tbody.appendChild(tr);
  }
}

function toggleWledFields(isPwm) {
  for (const id of ['s-host-label', 's-port-label', 's-count-label']) {
    $(id).hidden = isPwm;
  }
  $('s-pwm-note').hidden = !isPwm;
}

function selectStrip(s) {
  $('s-id').value = s.id;
  $('s-name').value = s.name;
  toggleWledFields(s.kind === 'pwm');
  if (s.kind === 'wled') {
    $('s-host').value = s.host;
    $('s-port').value = s.port;
    $('s-count').value = s.count;
  }
  $('s-update').disabled = false;
}

function dismissStrip() {
  $('s-id').value = '';
  $('s-name').value = '';
  toggleWledFields(false);
  $('s-update').disabled = true;
}

$('strip-form').onsubmit = async (ev) => {
  ev.preventDefault();
  const res = await fetch('/api/strips', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: $('s-name').value,
      host: $('s-host').value,
      port: Number($('s-port').value),
      count: Number($('s-count').value),
    }),
  });
  if (!res.ok) alert((await res.json()).detail);
  dismissStrip();
  await loadAll();
};

$('s-update').onclick = async () => {
  const id = $('s-id').value;
  if (!id) return;
  const s = strips.find((x) => String(x.id) === id);
  const body = { name: $('s-name').value };
  if (s && s.kind === 'wled') {
    body.host = $('s-host').value;
    body.port = Number($('s-port').value);
    body.count = Number($('s-count').value);
  }
  const res = await fetch(`/api/strips/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) alert((await res.json()).detail);
  dismissStrip();
  await loadAll();
};

$('s-dismiss').onclick = dismissStrip;

/* ---------- object types ---------- */

function renderTypes() {
  const tbody = document.querySelector('#types-table tbody');
  tbody.innerHTML = '';
  for (const t of types) {
    const used = t.used_by;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${escapeHtml(t.name)}</td>
      <td><code>${t.rule}</code></td>
      <td>${used}</td>
      <td class="row-actions"></td>`;
    const del = document.createElement('button');
    del.textContent = 'Delete';
    del.className = 'danger small';
    del.disabled = used > 0;
    del.title = used > 0 ? 'In use: cannot delete' : '';
    del.onclick = async (ev) => {
      ev.stopPropagation();
      if (!confirm(`Delete type "${t.name}"?`)) return;
      const res = await fetch(`/api/types/${encodeURIComponent(t.name)}`, { method: 'DELETE' });
      if (!res.ok) alert((await res.json()).detail);
      await loadAll();
    };
    tr.querySelector('.row-actions').appendChild(del);
    tr.onclick = () => selectType(t);
    tbody.appendChild(tr);
  }
}

function selectType(t) {
  $('t-original').value = t.name;
  $('t-name').value = t.name;
  $('t-rule').value = t.rule;
  $('rule-help').textContent = RULE_INFO[t.rule] || '';
  $('t-update').disabled = false;
}

function dismissType() {
  $('t-original').value = '';
  $('t-name').value = '';
  $('t-update').disabled = true;
}

$('type-form').onsubmit = async (ev) => {
  ev.preventDefault();
  const res = await fetch('/api/types', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: $('t-name').value, rule: $('t-rule').value }),
  });
  if (!res.ok) alert((await res.json()).detail);
  dismissType();
  await loadAll();
};

$('t-update').onclick = async () => {
  const original = $('t-original').value;
  if (!original) return;
  const res = await fetch(`/api/types/${encodeURIComponent(original)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: $('t-name').value, rule: $('t-rule').value }),
  });
  if (!res.ok) alert((await res.json()).detail);
  dismissType();
  await loadAll();
};

$('t-dismiss').onclick = dismissType;

/* ---------- simulator ---------- */

function buildSimPanel() {
  const panel = $('sim-panel');
  panel.innerHTML = '';
  for (const e of elements) {
    const offsets = SIM_OFFSETS[e.rule];
    if (!offsets) continue; // derived: no registers of its own
    const mb = e.modbus;
    for (const { off, label } of offsets) {
      const addr = mb.address + off;
      const row = document.createElement('div');
      row.className = 'sim-row';
      row.innerHTML = `<span class="name">${escapeHtml(e.name)}: ${label} (${escapeHtml(mb.host)} @${addr})</span>`;
      for (const val of [1, 0]) {
        const btn = document.createElement('button');
        btn.textContent = val ? 'ON (1)' : 'OFF (0)';
        if (val) btn.classList.add('on');
        btn.onclick = async () => {
          await fetch('/api/modbus/write', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              host: mb.host, port: mb.port, unit: mb.unit, address: addr, value: val,
            }),
          });
          await fetch('/api/refresh', { method: 'POST' });
        };
        row.appendChild(btn);
      }
      panel.appendChild(row);
    }
  }
}

/* ---------- init ---------- */

loadAll();
