/* Switchboard Mimic — página de Settings: tipos de objeto + simulador PLC */

const RULE_INFO = {
  simple: 'Lectura Modbus: registro[0]=1 → Rojo, si no → Verde.',
  breaker: 'Lectura Modbus: registro[2]=1 → Amarillo (disparado), registro[1]=1 → Rojo, registro[0]=1 → Verde, si no → Gris.',
  bus: 'Como "simple", y además marca este elemento como Bus de referencia para los tipos derivados.',
  derived: 'Sin lectura Modbus: Rojo si el Bus de referencia está Rojo y el elemento aguas arriba (el segmento que termina justo antes) está Rojo; si no → Verde.',
};

// Offsets sobre la dirección base del elemento, según su regla
const SIM_OFFSETS = {
  breaker: [
    { off: 0, label: 'cerrado' },
    { off: 1, label: 'abierto' },
    { off: 2, label: 'disparado' },
  ],
  simple: [{ off: 0, label: 'estado' }],
  bus: [{ off: 0, label: 'estado' }],
};

let types = [];
let rules = [];
let elements = [];

const $ = (id) => document.getElementById(id);

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/* ---------- tipos ---------- */

async function loadAll() {
  const [tRes, eRes] = await Promise.all([fetch('/api/types'), fetch('/api/elements')]);
  const tData = await tRes.json();
  types = tData.types;
  rules = tData.rules;
  elements = (await eRes.json()).elements;

  const sel = $('t-rule');
  if (!sel.options.length) {
    sel.innerHTML = rules.map((r) => `<option>${r}</option>`).join('');
    sel.onchange = () => { $('rule-help').textContent = RULE_INFO[sel.value] || ''; };
    sel.onchange();
  }
  renderTypes();
  buildSimPanel();
}

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
    del.textContent = 'Borrar';
    del.className = 'danger small';
    del.disabled = used > 0;
    del.title = used > 0 ? 'En uso: no se puede borrar' : '';
    del.onclick = async (ev) => {
      ev.stopPropagation();
      if (!confirm(`¿Borrar el tipo "${t.name}"?`)) return;
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

/* ---------- simulador ---------- */

function buildSimPanel() {
  const panel = $('sim-panel');
  panel.innerHTML = '';
  for (const e of elements) {
    const offsets = SIM_OFFSETS[e.rule];
    if (!offsets) continue; // derived: sin registros propios
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
