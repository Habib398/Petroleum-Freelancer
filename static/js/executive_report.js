(function(){
  const $ = (id)=>document.getElementById(id);

  function fmt(n){
    try{ return (Number(n)||0).toLocaleString('es-MX'); }catch(e){ return String(n||0); }
  }

  function ymd(d){
    const z = new Date(d);
    const y = z.getFullYear();
    const m = String(z.getMonth()+1).padStart(2,'0');
    const da = String(z.getDate()).padStart(2,'0');
    return `${y}-${m}-${da}`;
  }

  async function loadStations(){
    const r = await fetch('/api/stations');
    const j = await r.json();
    const sel = $('station');
    sel.innerHTML = '';
    const opt0 = document.createElement('option');
    opt0.value = '';
    opt0.textContent = 'Todas';
    sel.appendChild(opt0);
    (j.stations||[]).forEach(st=>{
      const o = document.createElement('option');
      o.value = st.id;
      o.textContent = `${st.name} (${st.code})`;
      sel.appendChild(o);
    });
  }

  function card(title, value, hint){
    const div = document.createElement('div');
    div.className='card';
    div.innerHTML = `
      <div class="help" style="letter-spacing:.12em;font-weight:900;">${title}</div>
      <div style="font-size:26px;font-weight:1000;margin-top:6px;">${fmt(value)}</div>
      <div class="help" style="margin-top:6px;">${hint||''}</div>
    `;
    return div;
  }

  function drawBars(canvas, items){
    if(!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || 800;
    const cssH = 260;
    canvas.width = Math.floor(cssW * dpr);
    canvas.height = Math.floor(cssH * dpr);
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    // clear
    ctx.clearRect(0,0,cssW,cssH);

    const padL = 44;
    const padR = 14;
    const padT = 14;
    const padB = 80;
    const w = cssW - padL - padR;
    const h = cssH - padT - padB;
    const baseX = padL;
    const baseY = padT + h;

    const vals = items.map(x=>Number(x.value)||0);
    let maxV = Math.max(1, ...vals);
    if(maxV <= 0) maxV = 1;

    // axes
    ctx.lineWidth = 1;
    ctx.strokeStyle = '#1f2a3a';
    ctx.beginPath();
    ctx.moveTo(baseX, padT);
    ctx.lineTo(baseX, baseY);
    ctx.lineTo(baseX + w, baseY);
    ctx.stroke();

    // grid + y labels
    ctx.fillStyle = '#6b7280';
    ctx.font = '12px system-ui, -apple-system, Segoe UI, Roboto, Arial';
    const steps = 4;
    for(let i=0;i<=steps;i++){
      const y = padT + (h * (i/steps));
      const v = Math.round(maxV * (1 - i/steps));
      ctx.strokeStyle = 'rgba(31,42,58,0.15)';
      ctx.beginPath();
      ctx.moveTo(baseX, y);
      ctx.lineTo(baseX + w, y);
      ctx.stroke();
      ctx.fillText(String(v), 6, y + 4);
    }

    const n = items.length || 1;
    const gap = 10;
    const barW = Math.max(18, (w - gap*(n+1)) / n);
    let x = baseX + gap;

    // bars
    ctx.fillStyle = '#0f172a';
    ctx.strokeStyle = '#0f172a';
    items.forEach(it=>{
      const v = Number(it.value)||0;
      const bh = (v/maxV) * (h-6);
      const y = baseY - bh;
      ctx.globalAlpha = 0.15;
      ctx.fillRect(x, y, barW, bh);
      ctx.globalAlpha = 1;
      ctx.strokeRect(x, y, barW, bh);

      // value
      ctx.fillStyle = '#111827';
      ctx.font = '12px system-ui, -apple-system, Segoe UI, Roboto, Arial';
      ctx.textAlign = 'center';
      ctx.fillText(String(v), x + barW/2, y - 4);

      // label (rotated)
      const label = String(it.label||'');
      ctx.save();
      ctx.translate(x + barW/2, baseY + 10);
      ctx.rotate(-Math.PI/4);
      ctx.fillStyle = '#374151';
      ctx.font = '12px system-ui, -apple-system, Segoe UI, Roboto, Arial';
      ctx.textAlign = 'right';
      ctx.fillText(label, 0, 0);
      ctx.restore();

      x += barW + gap;
    });
  }

  async function loadSemaphore(){
    const box = $('semaphore');
    if(!box) return;
    try{
      const r = await fetch('/api/admin/semaphore');
      const j = await r.json();
      const rows = (j.rows||[]).slice(0,10);
      box.innerHTML = rows.length ? rows.map(r=>`<div style="display:grid;grid-template-columns:80px 1fr 70px;gap:10px;padding:8px 0;border-bottom:1px solid rgba(2,6,23,.08)"><div><span class="tag ${r.color==='red'?'bad':r.color==='yellow'?'warn':'ok'}">${r.color.toUpperCase()}</span></div><div><b>${r.code}</b> · ${r.name}<div class="help">Alertas ${r.alerts_open} · Pagos ${r.payments_pending} · Docs ${r.docs_pending}</div></div><div style="text-align:right;font-weight:900">${r.score}</div></div>`).join('') : 'Sin estaciones.';
    }catch(e){ box.textContent = 'No fue posible cargar el semáforo.'; }
  }

  async function loadTrends(){
    const box = $('trends');
    if(!box) return;
    try{
      const r = await fetch('/api/admin/kpi-trends');
      const j = await r.json();
      const rows = j.rows||[];
      box.innerHTML = rows.length ? rows.map(r=>`<div style="display:grid;grid-template-columns:88px 1fr;gap:10px;padding:8px 0;border-bottom:1px solid rgba(2,6,23,.08)"><div><b>${r.month}</b></div><div>Alertas <b>${r.alerts}</b> · Entregas <b>${r.submissions}</b> · Docs <b>${r.docs}</b></div></div>`).join('') : 'Sin datos.';
    }catch(e){ box.textContent = 'No fue posible cargar tendencias.'; }
  }

  async function refresh(){
    const from = $('dFrom').value;
    const to = $('dTo').value;
    const sid = $('station').value;
    const qs = new URLSearchParams();
    if(from) qs.set('from', from);
    if(to) qs.set('to', to);
    if(sid) qs.set('station_id', sid);
    const url = '/api/admin/executive/summary?' + qs.toString();
    const r = await fetch(url);
    const j = await r.json();
    if(!j.ok){
      $('detail').textContent = 'Error: ' + (j.error||'unknown');
      return;
    }

    const m = j.metrics||{};
    const cards = $('cards');
    cards.innerHTML='';
    cards.appendChild(card('ALERTAS ABIERTAS', m.alerts_open, 'Total actual'));
    cards.appendChild(card('MANTENIMIENTOS', m.maintenance_created, 'Creados en el rango'));
    cards.appendChild(card('PIPAS', m.pipas_created, 'Creadas en el rango'));
    cards.appendChild(card('EVENTOS', m.events_planned, 'Programados en el rango'));

    const sub = m.submissions||{};
    cards.appendChild(card('ENTREGAS APROBADAS', sub.approved, 'En el rango'));
    cards.appendChild(card('ENTREGAS RECHAZADAS', sub.rejected, 'En el rango'));
    cards.appendChild(card('PAGOS PENDIENTES', m.payments_pending, 'Total actual'));
    cards.appendChild(card('DOCS POR VENCER', m.docs_expiring_30d, 'Próx. 30 días'));

    cards.appendChild(card('SASISOPA POR REVISAR', m.sasisopa_pending_review, 'Pendientes'));
    cards.appendChild(card('SGM POR REVISAR', m.sgm_pending_review, 'Pendientes'));

    const st = j.station ? `${j.station.name} (${j.station.code})` : 'Todas';
    $('detail').innerHTML = `Rango <b>${j.range.from}</b> a <b>${j.range.to}</b> · Estación: <b>${st}</b>`;

    const exp = new URLSearchParams(qs);
    $('btnExport').href = '/api/admin/executive/export.xlsx?' + exp.toString();
    $('btnExportPdf').href = '/api/admin/executive/export.pdf?' + exp.toString();

    // Build bar items from metrics
    const bars = [
      {label:'Alertas', value:m.alerts_created},
      {label:'Manten.', value:m.maintenance_created},
      {label:'Pipas', value:m.pipas_created},
      {label:'Eventos', value:m.events_planned},
      {label:'Aprob.', value:(sub.approved||0)},
      {label:'Rech.', value:(sub.rejected||0)},
      {label:'Pagos', value:m.payments_pending},
      {label:'Docs 30d', value:m.docs_expiring_30d},
      {label:'SASISOPA', value:m.sasisopa_pending_review},
      {label:'SGM', value:m.sgm_pending_review},
    ];
    drawBars($('bars'), bars);
  }


  async function loadAdvancedCharts(){
    try{
      const r = await fetch('/api/admin/dashboard/charts');
      const j = await r.json();
      const st = (j.station_breakdown||[]).slice(0,8).map(x=>({label:x.station, value:(Number(x.alerts||0)+Number(x.tasks||0))}));
      drawBars($('stationBars'), st.length?st:[{label:'Sin datos', value:0}]);
      const status = [];
      const task = j.task_status||{};
      ['open','in_progress','done','cancelled'].forEach(k=>{
        const v = Number(task[k]||0);
        if(v>0) status.push({label:k, value:v});
      });
      drawBars($('statusBars'), status.length?status:[{label:'Sin datos', value:0}]);
    }catch(e){}
  }

  async function init(){
    const today = new Date();
    const from = new Date(today.getTime() - 30*24*3600*1000);
    $('dFrom').value = ymd(from);
    $('dTo').value = ymd(today);
    await loadStations();
    $('btnRefresh').addEventListener('click', refresh);
    $('station').addEventListener('change', refresh);
    $('dFrom').addEventListener('change', refresh);
    $('dTo').addEventListener('change', refresh);
    await refresh();
    await loadSemaphore();
    await loadTrends();
    await loadAdvancedCharts();
  }

  init();
})();
