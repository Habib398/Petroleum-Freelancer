/* admin_menu.js – lógica del menú admin (búsqueda + métricas + notificaciones) */

async function safeJson(url){
  try{
    const r = await fetch(url, {headers:{"Accept":"application/json"}});
    if(!r.ok) return null;
    return await r.json();
  }catch(_){ return null; }
}

// ── Barra de búsqueda (Ctrl+K) ─────────────────────────────────────────────
(()=>{
  const searchInput = document.getElementById('searchInput');
  if(!searchInput) return;
  const items = [
    { text: 'SGM', href: '/admin/sgm', category: 'Módulos principales' },
    { text: 'SASISOPA', href: '/admin/sasisopa', category: 'Módulos principales' },
    { text: 'Estaciones', href: '/admin/stations', category: 'Módulos principales' },
    { text: 'Inbox', href: '/admin/inbox', category: 'Revisión' },
    { text: 'Documentos por validar', href: '/admin/pending-docs', category: 'Documentos' },
    { text: 'Centro documental', href: '/admin/document-center', category: 'Documentos' },
    { text: 'Usuarios', href: '/admin/users', category: 'Administración' },
    { text: 'Auditoría', href: '/admin/audit', category: 'Control' },
    { text: 'Configuración', href: '/admin/setup-wizard', category: 'Administración' }
  ];
  searchInput.addEventListener('keydown', (e)=>{
    if(e.key === 'Enter'){
      const query = searchInput.value.toLowerCase().trim();
      const match = items.find(i => i.text.toLowerCase().includes(query));
      if(match) window.location.href = match.href;
    }
  });
  document.addEventListener('keydown', (e)=>{
    if((e.ctrlKey || e.metaKey) && e.key === 'k'){
      e.preventDefault();
      searchInput.focus();
    }
  });
})();

// ── Métricas del hub + notificaciones ─────────────────────────────────────
(async ()=>{
  const m = await safeJson('/api/admin/hub-metrics');
  if(m && m.ok){
    const set = (id, value)=>{ const el=document.getElementById(id); if(el) el.textContent = value; };
    set('mStations', m.stations_active);
    set('mAlerts', `${m.alerts_open} (rojas: ${m.alerts_red_open})`);
    set('mReviews', m.reviews_pending);
    set('mToday', `${m.pending_today} / ${m.events_today}`);
  }
  const n = await safeJson('/api/notifications?unread=1');
  let unread = 0;
  if(Array.isArray(n)) unread = n.filter(x=>x && x.is_read===0).length;
  else if(n && Array.isArray(n.items)) unread = n.items.filter(x=>x && x.is_read===0).length;
  else if(n && Array.isArray(n.notifications)) unread = n.notifications.filter(x=>x && (x.is_read===0 || x.is_read===null)).length;
  else if(n && typeof n.unread_count === 'number') unread = n.unread_count;
  const dot = document.getElementById('notifDot');
  if(dot && unread>0){
    dot.textContent = unread>99 ? '99+' : String(unread);
    dot.style.display = 'grid';
  }
})();
