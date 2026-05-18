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
    eventClick(info){
      if(info.event.url){ info.jsEvent.preventDefault(); window.location.href=info.event.url; }
    },
    events:[]
  });
  cal.render();

  async function load(){
    const data = await api(`/api/operational-calendar?from=${encodeURIComponent(fromEl.value)}&to=${encodeURIComponent(toEl.value)}`);
    const items = data.items || [];
    cal.removeAllEvents();
    items.forEach(it=>{
      // FullCalendar: end es exclusivo, sumar 1 día para que el último día quede visible
      let endVal = undefined;
      if(it.end_date && it.end_date !== it.date){
        try{
          const d = new Date(it.end_date + 'T00:00:00');
          d.setDate(d.getDate()+1);
          endVal = d.toISOString().slice(0,10);
        }catch(e){}
      }
      cal.addEvent({
        title: it.title,
        start: it.date,
        end: endVal,
        color: it.color,
        url: it.url || null,
      });
    });
    listEl.innerHTML = items.length
      ? items.map(it=>{
          const dateLabel = (it.end_date && it.end_date !== it.date)
            ? `<b>${_esc(it.date||'')}</b> → <span style="color:#7c3aed">${_esc(it.end_date)}</span>`
            : `<b>${_esc(it.date||'')}</b>`;
          return `<div style="display:grid;grid-template-columns:200px 100px 1fr;gap:10px;padding:8px 0;border-bottom:1px solid rgba(2,6,23,.08)">
            <div>${dateLabel}</div>
            <div>${_esc(it.kind||'')}</div>
            <div>${it.url ? `<a href="${_esc(it.url)}">${_esc(it.title)}</a>` : _esc(it.title)}</div>
          </div>`;
        }).join('')
      : 'Sin eventos en el rango.';
  }

  qs('#btnReload').addEventListener('click', load);
  await load();
})();
