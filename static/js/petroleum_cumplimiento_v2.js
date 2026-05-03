(function(){
  const $ = (q)=>document.querySelector(q);

  const fuelSelect = $("#fuelSelect");
  const normsList = $("#normsList");

  const csrf = (document.querySelector('meta[name="csrf-token"]')||{}).getAttribute?.('content');

  async function api(url, opts={}){
    opts.headers = opts.headers || {};
    if(csrf) opts.headers["X-CSRF-Token"] = csrf;
    // JSON helper
    const res = await fetch(url, opts);
    const data = await res.json().catch(()=>({ok:false, message:"Respuesta inválida"}));
    if(!res.ok || data.ok===false){
      const msg = data.message || ("Error HTTP " + res.status);
      throw new Error(msg);
    }
    return data;
  }

  function esc(s){ return (s??"").toString().replace(/[&<>"']/g,(c)=>({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;" }[c])); }

  function bytesToHuman(bytes){
    if(bytes==null) return "";
    const u=["B","KB","MB","GB"]; let i=0; let b=Number(bytes);
    while(b>=1024 && i<u.length-1){ b/=1024; i++; }
    return (i===0? b : b.toFixed(1))+" "+u[i];
  }

  function render(items, fuel){
    if(!items || !items.length){
      normsList.innerHTML = `<div class="pc-empty">
        <div class="pc-empty-title">Sin documentos para ${esc(fuel)}</div>
        <div class="pc-help">Sube la primera versión para comenzar.</div>
      </div>`;
      return;
    }

    normsList.innerHTML = items.map(it=>{
      const ver = it.version ? `v${it.version}` : "—";
      const date = it.uploaded_at ? new Date(it.uploaded_at).toLocaleString() : "—";
      const file = it.original_name ? esc(it.original_name) : "—";
      const url = it.url ? it.url : null;

      const canUpload = (normsList.getAttribute("data-can-upload") === "1");

      return `<div class="pc-norm-card" data-key="${esc(it.doc_key)}">
        <div class="pc-norm-head">
          <div>
            <div class="pc-norm-title">${esc(it.title || it.doc_key)}</div>
            <div class="pc-norm-meta">
              <span class="pc-pill">${esc(ver)}</span>
              <span class="pc-meta">Actualizado: ${esc(date)}</span>
            </div>
          </div>
          <div class="pc-norm-actions">
            ${url ? `<a class="btn outline" href="${esc(url)}" target="_blank" rel="noopener">Descargar</a>` : `<span class="pc-muted">Sin archivo</span>`}
          </div>
        </div>

        <div class="pc-norm-foot">
          <div class="pc-file">${file}</div>
          <div class="pc-foot-actions">
            ${canUpload ? `<label class="btn primary">
              Subir / Actualizar
              <input type="file" class="pc-file-input" data-key="${esc(it.doc_key)}" accept=".pdf,.png,.jpg,.jpeg" />
            </label>` : ``}
          </div>
        </div>
      </div>`;
    }).join("");

    // bind inputs
    normsList.querySelectorAll(".pc-file-input").forEach(inp=>{
      inp.addEventListener("change", async ()=>{
        const f = inp.files && inp.files[0];
        if(!f) return;
        const key = inp.getAttribute("data-key");
        const fd = new FormData();
        fd.append("fuel", fuelSelect.value);
        fd.append("doc_key", key);
        fd.append("file", f);

        try{
          inp.closest(".pc-norm-card")?.classList.add("loading");
          await api("/api/petroleum/norms/upload", { method:"POST", body: fd });
          await load();
        }catch(e){
          alert(e.message || "No se pudo subir.");
        }finally{
          inp.value = "";
          inp.closest(".pc-norm-card")?.classList.remove("loading");
        }
      });
    });
  }

  async function load(){
    normsList.innerHTML = `<div class="pc-help">Cargando…</div>`;
    const fuel = fuelSelect.value || "magna";
    const data = await api(`/api/petroleum/norms?fuel=${encodeURIComponent(fuel)}`);
    render(data.items || [], data.fuel || fuel);
  }

  fuelSelect?.addEventListener("change", ()=>{ load().catch(e=>alert(e.message||"Error")); });

  // init
  if(fuelSelect){
    load().catch(e=>{
      normsList.innerHTML = `<div class="pc-empty"><div class="pc-empty-title">Error</div><div class="pc-help">${esc(e.message||"No se pudo cargar")}</div></div>`;
    });
  }
})();