(async()=>{
  const fromEl = qs('#dFrom');
  const toEl = qs('#dTo');
  const listEl = qs('#list');
  const today = new Date();
  const first = new Date(today.getFullYear(), today.getMonth(), 1);
  const next = new Date(today.getFullYear(), today.getMonth()+1, 0);
  fromEl.value = first.toISOString().slice(0,10);
  toEl.value = next.toISOString().slice(0,10);

  const cal = new FullCalendar.Calendar(qs('#calendar'), {
    initialView:'dayGridMonth',
    locale:'es',
    height:700,
    events:[]
  });
  cal.render();

  async function load(){
    const data = await api(`/api/operational-calendar?from=${encodeURIComponent(fromEl.value)}&to=${encodeURIComponent(toEl.value)}`);
    const items = data.items || [];
    cal.removeAllEvents();
    items.forEach(it=> cal.addEvent({ title: it.title, start: it.date, color: it.color, url: it.url }));
    listEl.innerHTML = items.length ? items.map(it=>`<div style="display:grid;grid-template-columns:120px 120px 1fr;gap:10px;padding:8px 0;border-bottom:1px solid rgba(2,6,23,.08)"><div><b>${_esc(it.date||'')}</b></div><div>${_esc(it.kind||'')}</div><div>${it.url ? `<a href="${_esc(it.url)}">${_esc(it.title)}</a>` : _esc(it.title)}</div></div>`).join('') : 'Sin eventos en el rango.';
  }

  qs('#btnReload').addEventListener('click', load);
  await load();
})();
