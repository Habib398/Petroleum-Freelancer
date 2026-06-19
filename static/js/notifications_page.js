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
        <div class="notif-item ${isRead?'notif-read':'notif-unread'}">
          <div class="notif-indicator"></div>
          <div class="notif-body">
            <div class="notif-title">${title}</div>
            ${body?`<div class="notif-desc">${body}</div>`:""}
            <div class="notif-time">${when}</div>
          </div>
          <div class="notif-actions">
            ${url?`<a class="btn small" href="${url}">Abrir</a>`:""}
            ${isRead?"":`<button class="btn small ghost" data-read="${n.id}">Marcar</button>`}
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
