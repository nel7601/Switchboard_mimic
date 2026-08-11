/* Switchboard Mimic — vista de Elementos */

let elements = [];
let types = [];

const $ = (id) => document.getElementById(id);

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function ruleOf(typeName) {
  const t = types.find((t) => t.name === typeName);
  return t ? t.rule : 'simple';
}

async function loadAll() {
  const res = await fetch('/api/elements');
  const data = await res.json();
  elements = data.elements;
  types = data.types;

  const sel = $('e-type');
  const current = sel.value;
  sel.innerHTML = types.map((t) => `<option>${escapeHtml(t.name)}</option>`).join('');
  if (types.some((t) => t.name === current)) sel.value = current;
  toggleModbusFields();
  renderTable();
}

function toggleModbusFields() {
  const derived = ruleOf($('e-type').value) === 'derived';
  $('modbus-fields').hidden = derived;
  $('modbus-note').hidden = !derived;
}

function renderTable() {
  const tbody = document.querySelector('#elements-table tbody');
  tbody.innerHTML = '';
  for (const e of elements) {
    const derived = e.rule === 'derived';
    const mb = e.modbus || {};
    const tr = document.createElement('tr');
    tr.dataset.id = e.id;
    tr.innerHTML = `
      <td>${e.id}</td>
      <td>${escapeHtml(e.name)}</td>
      <td>${escapeHtml(e.type)} <code>${e.rule}</code></td>
      <td>${derived ? '—' : escapeHtml(mb.host)}</td>
      <td>${derived ? '—' : mb.port}</td>
      <td>${derived ? '—' : mb.unit}</td>
      <td>${derived ? '—' : mb.address}</td>
      <td>${e.used_by}</td>
      <td class="row-actions"></td>`;
    const del = document.createElement('button');
    del.textContent = 'Borrar';
    del.className = 'danger small';
    del.disabled = e.used_by > 0;
    del.title = e.used_by > 0 ? 'Asignado en el mímico: no se puede borrar' : '';
    del.onclick = async (ev) => {
      ev.stopPropagation();
      if (!confirm(`¿Borrar el elemento "${e.name}"?`)) return;
      const res = await fetch(`/api/elements/${e.id}`, { method: 'DELETE' });
      if (!res.ok) alert((await res.json()).detail);
      await loadAll();
    };
    tr.querySelector('.row-actions').appendChild(del);
    tr.onclick = () => selectElement(e);
    tbody.appendChild(tr);
  }
}

function selectElement(e) {
  $('e-id').value = e.id;
  $('e-name').value = e.name;
  $('e-type').value = e.type;
  const mb = e.modbus || {};
  $('e-host').value = mb.host ?? '127.0.0.1';
  $('e-port').value = mb.port ?? 502;
  $('e-unit').value = mb.unit ?? 1;
  $('e-address').value = mb.address ?? 0;
  $('e-update').disabled = false;
  toggleModbusFields();
  document.querySelectorAll('#elements-table tbody tr').forEach((tr) =>
    tr.classList.toggle('selected', Number(tr.dataset.id) === e.id));
}

function dismiss() {
  $('e-id').value = '';
  $('e-name').value = '';
  $('e-update').disabled = true;
  document.querySelectorAll('#elements-table tbody tr').forEach((tr) =>
    tr.classList.remove('selected'));
}

function formPayload() {
  return {
    name: $('e-name').value,
    type: $('e-type').value,
    modbus: {
      host: $('e-host').value,
      port: Number($('e-port').value),
      unit: Number($('e-unit').value),
      address: Number($('e-address').value),
    },
  };
}

$('e-type').addEventListener('change', toggleModbusFields);

$('element-form').onsubmit = async (ev) => {
  ev.preventDefault();
  const res = await fetch('/api/elements', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formPayload()),
  });
  if (!res.ok) alert((await res.json()).detail);
  dismiss();
  await loadAll();
};

$('e-update').onclick = async () => {
  const id = $('e-id').value;
  if (!id) return;
  const res = await fetch(`/api/elements/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formPayload()),
  });
  if (!res.ok) alert((await res.json()).detail);
  dismiss();
  await loadAll();
};

$('e-dismiss').onclick = dismiss;

loadAll();
