(async ()=>{
  const esc = (typeof _esc === "function") ? _esc : (v=>String(v ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/\"/g,"&quot;").replace(/'/g,"&#39;"));
  async function load(){
    let data;
    try{
      data = await api("/api/notifications");
    }catch(e){
      const list = qs("#notifList");
      const empty = qs("#notifEmpty");
      if (list) list.innerHTML = "";
      if (empty){
        empty.hidden = false;
        empty.textContent = "No se pudieron cargar las notificaciones: " + (e?.message || "error");
      }
      toast("Error", "No se pudieron cargar las notificaciones.");
      return;
    }
    const list = qs("#notifList");
    const empty = qs("#notifEmpty");
    const items = data.notifications || [];
    if (!items.length){
      list.innerHTML = "";
      empty.hidden = false;
      return;
    }
    empty.hidden = true;
    list.innerHTML = items.map(n=>{
      const isRead = !!n.is_read;
      const title = esc(n.title||"Notificación");
      const body = esc(n.body||"");
      const when = (n.created_at||"").replace("T"," ").slice(0,16);
      const url = String(n.url || "");
      return `
        <div class="card" style="margin:10px 0;opacity:${isRead?0.7:1};">
          <div style="display:flex;gap:10px;justify-content:space-between;align-items:flex-start;">
            <div>
              <div style="font-weight:900;">${title}</div>
              <div class="help">${when}</div>
              ${body?`<div style="margin-top:8px;">${body}</div>`:""}
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;">
              ${url?`<a class="btn small" href="${url}">Abrir</a>`:""}
              ${isRead?"":`<button class="btn small ghost" data-read="${n.id}">Leído</button>`}
            </div>
          </div>
        </div>
      `;
    }).join("");

    qsa("[data-read]").forEach(b=>b.addEventListener("click", async ()=>{
      await api(`/api/notifications/${b.dataset.read}/read`, {method:"POST"});
      await load();
    }));
  }

  qs("#btnReload")?.addEventListener("click", load);
  qs("#btnReadAll")?.addEventListener("click", async ()=>{
    await api("/api/notifications/read-all", {method:"POST"});
    toast("Listo","Todas las notificaciones quedaron como leídas.");
    await load();
  });

  await load();
})();
