(async ()=>{
  const err = qs("#sErr");

  function getCsrfToken(){
    // Prefer meta tag if present, else cookie set by backend
    const meta = document.querySelector('meta[name="csrf-token"]');
    if(meta && meta.content) return meta.content;
    // cookie parser
    const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    if(m) return decodeURIComponent(m[1]);
    // fallback: sometimes app sets window.__csrf
    // @ts-ignore
    if(window.__csrf) return window.__csrf;
    return "";
  }

  function dmsToDecimal(deg, min, sec, dir){
    let dec = Number(deg) + Number(min)/60 + Number(sec)/3600;
    if (dir === 'S' || dir === 'W') dec *= -1;
    return dec;
  }
  function parseCoord(raw){
    const s = (raw||"").trim();
    if(!s) return null;

    // Decimal formats: "lat,lng" or "lat lng"
    const decMatch = s.match(/(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)/);
    if (decMatch){
      const lat = Number(decMatch[1]);
      const lng = Number(decMatch[2]);
      if(!Number.isNaN(lat) && !Number.isNaN(lng)) return {lat, lng};
    }

    // DMS format: 25°40'11.97"N 100°18'05.72"W
    const r = /(\d+)°(\d+)'([\d.]+)\"?([NSEW])/gi;
    let m, vals=[];
    while((m=r.exec(s))!==null){
      vals.push(dmsToDecimal(m[1], m[2], m[3], m[4].toUpperCase()));
    }
    if (vals.length >= 2){
      return {lat: vals[0], lng: vals[1]};
    }
    return null;
  }

  let lastStations = [];
  async function refresh(){
    const st = (await api("/api/stations")).stations || [];
    lastStations = st;
    const tb = qs("#sT");
    tb.innerHTML = st.map(s=>`
      <tr>
        <td>${(s.station_number ?? s.id)}</td>
        <td><b>${s.name}</b><div class="muted">${s.city||""} ${s.state||""}</div></td>
        <td>${(s.brand||"consulting")==="petroleum" ? `<span class="pill pill-petroleum">Petroleum</span>` : `<span class="pill pill-consulting">Consulting</span>`}</td>
        <td>${s.group_name||""}</td>
        <td>${s.code}</td>
        <td>${s.monthly_status}</td>
        <td style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn ghost small" data-edit="${s.id}">Editar</button>
          <button class="btn danger small" data-del="${s.id}">Borrar</button>
          <span style="width:100%;height:0;"></span>
          <button class="btn ghost small" data-set="${s.id}" data-status="active">Activar</button>
          <button class="btn ghost small" data-set="${s.id}" data-status="view_only">Vista</button>
          <button class="btn ghost small" data-set="${s.id}" data-status="expired">Expirada</button>
        </td>
      </tr>
    `).join("");
    qsa("[data-set]").forEach(b=>b.addEventListener("click", async ()=>{
      await api(`/api/stations/${b.dataset.set}`,{method:"PUT",body:JSON.stringify({monthly_status:b.dataset.status})});
      toast("Actualizado","Status actualizado.");
      await refresh();
    }));
    qsa("[data-edit]").forEach(b=>b.addEventListener("click", ()=>{
  const s = lastStations.find(x=>String(x.id)===String(b.dataset.edit));
  if(!s) return;
  qs("#sId").value = s.id;
  qs("#sName").value = s.name||"";
  qs("#sCode").value = s.code||"";
  if(qs("#sBrand")) qs("#sBrand").value = (s.brand||"consulting");
  if(qs("#sMonthlyEnd")) qs("#sMonthlyEnd").value = (s.monthly_end||"");
  qs("#sNum").value = (s.station_number!=null? s.station_number: "");
  qs("#sGroup").value = s.group_name||"";
  qs("#sState").value = s.state||"";
  qs("#sCity").value = s.city||"";
  qs("#sAddr").value = s.address||"";
  qs("#sCoord").value = (s.lat!=null && s.lng!=null) ? `${s.lat}, ${s.lng}` : "";
  if (qs("#sCoord").value) syncLatLng();
  qs("#sAdd").textContent = "Guardar cambios";
  qs("#sCancelEdit").hidden = false;
  window.scrollTo({top:0, behavior:"smooth"});
}));
qsa("[data-del]").forEach(b=>b.addEventListener("click", async ()=>{
  const id = b.dataset.del;
  if(!confirm("¿Borrar estación? Esto eliminará también sus eventos y entregas relacionadas.")) return;
  await api(`/api/stations/${id}`, {method:"DELETE"});
  toast("Eliminada","Estación borrada.");
  await refresh();
}));

  }


  const sCoord = qs("#sCoord");
  function syncLatLng(){
    const res = parseCoord(sCoord?.value);
    if(res){
      qs("#sLat").value = res.lat.toFixed(6);
      qs("#sLng").value = res.lng.toFixed(6);
      return res;
    } else {
      qs("#sLat").value = "";
      qs("#sLng").value = "";
      return null;
    }
  }
  if (sCoord){
    sCoord.addEventListener("input", ()=>{ syncLatLng(); });
    sCoord.addEventListener("blur", ()=>{ syncLatLng(); });
  }

  // Map preview dialog
  const dlg = qs("#dlgStationMap");
  const btnPrev = qs("#sPreview");
  const btnClose = qs("#sMapClose");
  let map=null, marker=null;
  if(btnPrev && dlg){
    btnPrev.addEventListener("click", ()=>{
      const res = syncLatLng();
      if(!res){
        toast("Coordenada inválida","Pega una coordenada válida (DMS o decimal).");
        return;
      }
      dlg.showModal();
      setTimeout(()=>{
        if(!map){
          map = L.map('stationMap').setView([res.lat, res.lng], 12);
          L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap' }).addTo(map);
        }
        map.setView([res.lat, res.lng], 12);
        if(marker){ marker.remove(); }
        marker = L.marker([res.lat, res.lng]).addTo(map);
      }, 50);
    });
  }
  if(btnClose && dlg) btnClose.addEventListener("click", ()=> dlg.close());

  const btnCancelEdit = qs("#sCancelEdit");
  if(btnCancelEdit){
    btnCancelEdit.addEventListener("click", ()=>{
      qs("#sId").value="";
      qs("#sAdd").textContent="Crear";
      btnCancelEdit.hidden=true;
      ["#sName","#sCode","#sNum","#sGroup","#sState","#sCity","#sAddr","#sCoord","#sLat","#sLng"].forEach(sel=>{ const el=qs(sel); if(el) el.value=""; });
    });
  }

  qs("#sAdd").addEventListener("click", async ()=>{
    const editingId = (qs("#sId").value||"").trim();
    err.hidden=true;
    try{
      await api(editingId?`/api/stations/${editingId}`:"/api/stations",{method: editingId?"PUT":"POST",body:JSON.stringify({
        brand:(qs("#sBrand")?qs("#sBrand").value:"consulting"),
        name:qs("#sName").value, code:qs("#sCode").value,
        station_number: qs("#sNum").value? Number(qs("#sNum").value): null,
        group_name: qs("#sGroup").value,
        monthly_end: (qs("#sMonthlyEnd")?qs("#sMonthlyEnd").value:null),
        state:qs("#sState").value, city:qs("#sCity").value,
        address:qs("#sAddr").value,
        lat:qs("#sLat").value? Number(qs("#sLat").value): null,
        lng:qs("#sLng").value? Number(qs("#sLng").value): null
      })});
      toast(editingId?"Actualizada":"Creada", editingId?"Estación actualizada.":"Estación creada.");
      qs("#sId").value=""; qs("#sAdd").textContent="Crear"; qs("#sCancelEdit").hidden=true;
      ["#sName","#sCode","#sNum","#sGroup","#sState","#sCity","#sAddr","#sLat","#sLng"].forEach(id=>{const el=qs(id); if(el) el.value="";});
      await refresh();
    }catch(e){
      err.textContent="Error: "+e.message;
      err.hidden=false;
    }
  });


  // --- KML Import (Placemark/Point) ---
  const kmlBtn = qs("#kmlImport");
  const kmlFile = qs("#kmlFile");
  const kmlMsg = qs("#kmlMsg");
  if(kmlBtn && kmlFile){
    kmlBtn.addEventListener("click", async ()=>{
      kmlMsg && (kmlMsg.hidden=true);
      const f = (kmlFile.files||[])[0];
      if(!f){ toast("Falta archivo","Selecciona un .kml"); return; }
      const fd = new FormData();
      fd.append("file", f);
      kmlBtn.disabled = true;
      try{
        const r = await fetch("/api/stations/import-kml", {method:"POST", body: fd, credentials:"include", headers: {"X-CSRF-Token": getCsrfToken()}});
        const data = await r.json().catch(()=>({ok:false,error:"Respuesta inválida"}));
        if(!r.ok || !data.ok){
          const msg = data.error || ("Error HTTP " + r.status);
          if(kmlMsg){ kmlMsg.textContent = msg; kmlMsg.hidden=false; }
          toast("Error", msg);
          return;
        }
        const msg = `Importadas: ${data.count} · Omitidas: ${data.skipped}`;
        if(kmlMsg){ kmlMsg.textContent = msg; kmlMsg.hidden=false; }
        toast("Importación lista", msg);
        kmlFile.value = "";
        await refresh();
      }catch(e){
        const msg = e.message || "Error al importar";
        if(kmlMsg){ kmlMsg.textContent = msg; kmlMsg.hidden=false; }
        toast("Error", msg);
      }finally{
        kmlBtn.disabled = false;
      }
    });
  }

  await refresh();
})();
