(function(){
  const $ = (q)=>document.querySelector(q);
  const body = $("#stationsBody");
  const drawer = $("#drawer");
  const drawerStation = $("#drawerStation");
  const itemsGrid = $("#itemsGrid");

  function fmtStation(s){
    return `<div>
      <div class="station-code">${escapeHtml(s.code||('ID '+s.id))}</div>
      <div class="station-name">${escapeHtml(s.name||'')}</div>
    </div>`;
  }

  function escapeHtml(str){
    return String(str||'').replace(/[&<>"']/g, m=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m]));
  }

  function setKpis(stations){
    let pend=0, real=0, prog=0, late=0;
    stations.forEach(s=>{ pend+=s.pendientes||0; real+=s.realizadas||0; prog+=s.programadas||0; late+=s.fuera_plazo||0; });
    $("#kpiPend").textContent = pend;
    $("#kpiReal").textContent = real;
    $("#kpiProg").textContent = prog;
    $("#kpiLate").textContent = late;
  }

  async function load(){
    body.innerHTML = `<tr><td colspan="5" class="muted">Cargando…</td></tr>`;
    const r = await fetch("/api/calibraciones/summary");
    const j = await r.json();
    if(!j.ok){ body.innerHTML = `<tr><td colspan="5" class="muted">No se pudo cargar.</td></tr>`; return; }
    const stations = j.stations || [];
    setKpis(stations);
    renderStations(stations);
  }

  function renderStations(stations){
    const q = ($("#calSearch").value||"").trim().toLowerCase();
    const filtered = q ? stations.filter(s => (s.code||'').toLowerCase().includes(q) || (s.name||'').toLowerCase().includes(q)) : stations;
    if(!filtered.length){
      body.innerHTML = `<tr><td colspan="5" class="muted">Sin estaciones.</td></tr>`;
      return;
    }
    body.innerHTML = filtered.map(s=>{
      return `<tr>
        <td>${fmtStation(s)}</td>
        <td>
          <div class="pbar" aria-label="Avance"><span style="width:${s.pct||0}%"></span></div>
          <div class="muted" style="font-size:12px;margin-top:6px;font-weight:800;">${s.pct||0}%</div>
        </td>
        <td><span class="pill">⏳ ${s.pendientes||0}</span></td>
        <td><span class="pill">✅ ${s.realizadas||0}</span></td>
        <td><button class="btn primary" data-open="${s.id}">Ver / Editar</button></td>
      </tr>`;
    }).join("");

    body.querySelectorAll("[data-open]").forEach(btn=>{
      btn.addEventListener("click", ()=>openStation(btn.getAttribute("data-open")));
    });
  }

  async function openStation(stationId){
    const r = await fetch(`/api/calibraciones/station/${stationId}`);
    const j = await r.json();
    if(!j.ok){ alert("No se pudo abrir la estación"); return; }
    drawerStation.textContent = `${j.station.code || ('ID '+j.station.id)} — ${j.station.name || ''}`;
    itemsGrid.innerHTML = (j.items||[]).map(it=>{
      const tagClass = it.state === "done" ? "done" : "pending";
      const tagText = it.state === "done" ? "✅ Documento cargado" : "⏳ Pendiente";
      const current = it.current;
      const viewLink = current ? `<a class="small" href="${current.url}" target="_blank">Ver archivo (v${current.version_no||1})</a>` : "";
      const hist = it.history_count ? `<span class="muted" style="font-size:12px;">Historial: ${it.history_count}</span>` : "";
      return `<div class="item">
        <div class="item-top">
          <div>
            <h3>${escapeHtml(it.title)}</h3>
            <p>${escapeHtml(it.hint||"")}</p>
          </div>
          <span class="tag ${tagClass}">${tagText}</span>
        </div>

        <div class="item-actions">
          ${viewLink}
          <label class="small">Subir/Actualizar:</label>
          <input type="file" accept=".pdf,.png,.jpg,.jpeg" data-up="${stationId}" data-key="${escapeHtml(it.key)}" data-title="${escapeHtml(it.title)}">
          ${hist}
        </div>
      </div>`;
    }).join("");

    // bind uploads
    itemsGrid.querySelectorAll("input[type=file][data-up]").forEach(inp=>{
      inp.addEventListener("change", ()=>uploadDoc(inp));
    });

    drawer.setAttribute("aria-hidden","false");
  }

  async function uploadDoc(input){
    const file = input.files && input.files[0];
    if(!file) return;
    const stationId = input.getAttribute("data-up");
    const section = input.getAttribute("data-key");
    const title = input.getAttribute("data-title") || "Documento";

    const fd = new FormData();
    fd.append("module","calibraciones");
    fd.append("section", section);
    fd.append("title", title);
    fd.append("station_id", stationId);
    fd.append("file", file);

    const r = await fetch("/api/docs/upload", { method:"POST", body: fd });
    const j = await r.json().catch(()=>({ok:false}));
    if(!r.ok || !j.ok){
      alert(j.message || "No se pudo subir el archivo");
      return;
    }
    // refresh station view
    await openStation(stationId);
    input.value = "";
  }

  $("#drawerClose").addEventListener("click", ()=>drawer.setAttribute("aria-hidden","true"));
  $("#drawerX").addEventListener("click", ()=>drawer.setAttribute("aria-hidden","true"));
  $("#calSearch").addEventListener("input", ()=>load());
  $("#calSearchBtn").addEventListener("click", ()=>load());

  load();
})();
