(async ()=>{
  let me=null;
  try{ me=(await api("/api/me")).me; }catch(e){ return; }

  let calendar = null;
  const isPetroleum = document.body.classList.contains("brand-petroleum");
  const itemLabel = isPetroleum ? "agenda" : "actividad";
  const itemLabelCap = isPetroleum ? "Agenda" : "Actividad";
  let currentRange = {start:null,end:null};
  const btnNew = qs("#btnNew");
  const btnPrint = qs("#btnPrint");
  const btnPdf = qs("#btnPdf");

const btnImportProgram = qs("#btnImportProgram");

  if (btnPrint) btnPrint.addEventListener("click", ()=>{
    document.body.classList.add("print-calendar-only");
    window.print();
  });
  window.addEventListener("afterprint", ()=> document.body.classList.remove("print-calendar-only"));

  if (btnPdf) btnPdf.addEventListener("click", ()=>{
    const q = new URLSearchParams();
    if (currentRange.start) q.set("start", currentRange.start.slice(0,10));
    if (currentRange.end) q.set("end", currentRange.end.slice(0,10));
    if (filterState.freq) q.set("freq", filterState.freq);
    if (filterState.search) q.set("q", filterState.search);
    // open print view in new tab/window
    window.open("/mod/activities/print?" + q.toString(), "_blank");
  });

const dlgNew = qs("#dlgNew");

  // UI filters
  const fFreq = qs("#fFreq");
  const fSearch = qs("#fSearch");
  const fToday = qs("#fToday");

  let filterState = { freq:"", search:"", today:false };

  function applyFilterState(){
    filterState.freq = (fFreq?.value || "").trim();
    filterState.search = (fSearch?.value || "").trim().toLowerCase();
    filterState.today = !!(fToday?.checked);
    if (filterState.today){
      // Bring user to today for convenience
      try{ calendar?.today?.(); }catch(e){}
    }
    calendar?.refetchEvents?.();
  }

  if (fFreq) fFreq.addEventListener("change", applyFilterState);
  if (fToday) fToday.addEventListener("change", applyFilterState);
  if (fSearch) {
    fSearch.addEventListener("keydown", (e)=>{ if(e.key==="Enter"){ e.preventDefault(); applyFilterState(); } });
    fSearch.addEventListener("blur", applyFilterState);
  }


  async function loadStations(){
    const st = (await api("/api/stations")).stations || [];
    const sel = qs("#newStation");
    sel.innerHTML = `<option value="">(Todas las estaciones)</option>` + st.map(s=>`<option value="${s.id}">${s.code} • ${s.name}</option>`).join("");
  }

  if (me.role === "admin" && btnNew){
    if (btnImportProgram){
      btnImportProgram.hidden=false;
      const dlgImport = qs("#dlgImport");
      const formImport = qs("#formImport");
      const impCancel = qs("#impCancel");
      const impErr = qs("#impErr");
      btnImportProgram.addEventListener("click", ()=>{
        if (impErr) { impErr.hidden = true; impErr.textContent = ""; }
        if (formImport) formImport.reset();
        dlgImport && dlgImport.showModal();
      });
      if (impCancel) impCancel.addEventListener("click", ()=> dlgImport && dlgImport.close());
      if (formImport){
        formImport.addEventListener("submit", async (ev)=>{
          ev.preventDefault();
          if (impErr) { impErr.hidden = true; impErr.textContent = ""; }
          try{
            const fd = new FormData(formImport);
            await api("/api/import/activities", { method:"POST", body: fd });
            dlgImport && dlgImport.close();
            toast("Importado", isPetroleum ? "Agenda importada correctamente." : "Actividades importadas correctamente.");
            calendar && calendar.refetchEvents();
          }catch(e){
            const msg = (e && e.message) ? e.message : "No se pudo importar";
            if (impErr){ impErr.textContent = "Error: " + msg; impErr.hidden = false; }
            else toast("Error", msg, {type:"error"});
          }
        });
      }
    }

    btnNew.hidden=false;
    btnNew.addEventListener("click", async ()=>{
      await loadStations();
      qs("#newStart").value = new Date().toISOString().slice(0,10);
      qs("#newUntil").value = "";
      qs("#newRepeat").value = "daily";
      qs("#newTitle").value = "";
      qs("#newDesc").value = "";
      qs("#newErr").hidden=true;
      dlgNew.showModal();
    });
    qs("#newClose").addEventListener("click", ()=> dlgNew.close());

    const form = qs("#formNewActivity");
    form.addEventListener("submit", async (ev)=>{
      ev.preventDefault();
      const err = qs("#newErr");
      err.hidden=true;
      try{
        const fd = new FormData(form);
        await api("/api/activity-templates", { method:"POST", body: fd, headers:{} });
        dlgNew.close();
        toast("Creada", isPetroleum ? "Agenda creada y programada." : "Actividad creada y programada.");
        calendar.refetchEvents();
      }catch(e){
        err.textContent = "Error: " + e.message;
        err.hidden=false;
      }
    });
  }

  // FullCalendar
  const calEl = qs("#calendar");
  calendar = new FullCalendar.Calendar(calEl, {
    initialView: 'dayGridMonth',
    height: 'auto',
    locale: 'es',
    firstDay: 1,
    headerToolbar: { left: 'prev,next today', center: 'title', right: 'dayGridMonth,dayGridWeek,print' },
    editable: (me.role === 'admin'),
    eventStartEditable: (me.role === 'admin'),
    eventDurationEditable: false,
    droppable: false,
    customButtons: {
      print: {
        text: 'Imprimir',
        click: ()=> window.print()
      }
    },
    events: async (info, success, failure)=>{
      try{
        currentRange = {start: info.startStr, end: info.endStr};
        const url = `/api/calendar/events?start=${encodeURIComponent(info.startStr)}&end=${encodeURIComponent(info.endStr)}`;
        
        const data = await api(url);
        // client-side filters (freq, search, today)
        const todayStr = new Date().toISOString().slice(0,10);
        const filtered = (data||[]).filter(ev=>{
          const rk = (ev.extendedProps?.repeat_kind || "").toString();
          const baseTitle = ((ev.extendedProps?.base_title || ev.title || "") + "").toLowerCase();
          if (filterState.freq && rk !== filterState.freq) return false;
          if (filterState.search && !baseTitle.includes(filterState.search)) return false;
          if (filterState.today && (ev.start || "").slice(0,10) !== todayStr) return false;
          return true;
        });
        success(filtered);

      }catch(e){ failure(e); }
    },
    eventDrop: (arg)=>{
      // Admin-only drag & drop reschedule with confirmation
      if (me.role !== 'admin') { try{ arg.revert(); }catch(e){}; return; }
      const dlg = qs('#dlgMoveEvent');
      if (!dlg){ try{ arg.revert(); }catch(e){}; return; }
      const id = arg.event.id;
      const oldDate = (arg.oldEvent.start ? arg.oldEvent.start.toISOString().slice(0,10) : '');
      const newDate = (arg.event.start ? arg.event.start.toISOString().slice(0,10) : '');
      qs('#mvEventId').value = id;
      qs('#mvOldDate').value = oldDate;
      qs('#mvNewDate').value = newDate;
      qs('#mvInfo').textContent = `Mover: ${arg.event.title} • ${oldDate} → ${newDate}`;
      // default scope single
      (qsa('input[name="mvScope"]')||[]).forEach(r=>{ r.checked = (r.value==='single'); });
      dlg.showModal();
      // if dialog closes without saving, revert
      const onClose = ()=>{
        dlg.removeEventListener('close', onClose);
        // if user didn't confirm, revert
        if (!dlg.returnValue || dlg.returnValue==='cancel'){
          try{ arg.revert(); }catch(e){}
        }
      };
      dlg.addEventListener('close', onClose);
    },
    eventClick: (arg)=>{
      const id = arg.event.id;
      window.location.href = `/mod/activities/event/${id}`;
    }
  });
  
calendar.render();

// Move dialog save
const dlgMoveEvent = qs("#dlgMoveEvent");
if (dlgMoveEvent){
  qs("#mvSave")?.addEventListener("click", async (e)=>{
    e.preventDefault();
    const id = qs("#mvEventId").value;
    const oldDate = qs("#mvOldDate").value;
    const newDate = qs("#mvNewDate").value;
    const scope = (qsa('input[name="mvScope"]')||[]).find(r=>r.checked)?.value || "single";
    await api(`/api/calendar/events/${id}/move`, {method:"POST", body: JSON.stringify({ new_date: newDate, old_date: oldDate, scope })});
    toast("Actualizado", isPetroleum ? "Agenda reprogramada." : "Actividad reprogramada.");
    dlgMoveEvent.close("ok");
    calendar?.refetchEvents?.();
  });
}

// -------- Admin: manage activity templates --------
const actsCard = qs("[data-activity-manage-card]") || null;
const btnRefreshActs = qs("#btnRefreshActs");
const aT = qs("#aT");
const tplSearch = qs("#tplSearch");
const tplStatus = qs("#tplStatus");
const tplEmpty = qs("#tplEmpty");
const tplCount = qs("#tplCount");
const dlgActEdit = qs("#dlgActEdit");
const aeId = qs("#aeId"), aeTitle=qs("#aeTitle"), aeDesc=qs("#aeDesc"), aeEvidence=qs("#aeEvidence"), aeActive=qs("#aeActive");
let actCache = [];

function renderTplRows(){
  if (!aT) return;
  const term = (tplSearch?.value || "").trim().toLowerCase();
  const status = tplStatus?.value || "";
  const filtered = actCache.filter(a => {
    if (status === "active" && !a.is_active) return false;
    if (status === "inactive" && a.is_active) return false;
    if (term){
      const hay = `${a.title||""} ${a.description||""}`.toLowerCase();
      if (!hay.includes(term)) return false;
    }
    return true;
  });
  aT.innerHTML = filtered.map(a=>{
    const desc = (a.description||"").slice(0,140);
    const activeChip = a.is_active
      ? `<span class="tpl-chip on">Activa</span>`
      : `<span class="tpl-chip off">Inactiva</span>`;
    const evChip = a.evidence_required
      ? `<span class="tpl-chip on">Pide evidencia</span>`
      : `<span class="tpl-chip off">Sin evidencia</span>`;
    return `
      <tr>
        <td>
          <div class="tpl-title">${_esc(a.title)}</div>
          ${desc ? `<div class="tpl-desc">${_esc(desc)}${(a.description||"").length>140?"…":""}</div>` : ""}
        </td>
        <td>${activeChip}${evChip}</td>
        <td style="text-align:right;white-space:nowrap;">
          <button class="btn ghost small" data-aedit="${a.id}" type="button">Editar</button>
          <button class="btn danger small" data-adel="${a.id}" type="button">Borrar</button>
        </td>
      </tr>
    `;
  }).join("");

  if (tplEmpty) tplEmpty.hidden = filtered.length > 0;

  qsa("[data-aedit]").forEach(b=>b.addEventListener("click", ()=>{
    const id = Number(b.dataset.aedit);
    const a = actCache.find(x=>Number(x.id)===id);
    if(!a) return;
    aeId.value = a.id;
    aeTitle.value = a.title||"";
    aeDesc.value = a.description||"";
    aeEvidence.checked = !!a.evidence_required;
    aeActive.checked = !!a.is_active;
    dlgActEdit.showModal();
  }));
  qsa("[data-adel]").forEach(b=>b.addEventListener("click", async ()=>{
    const id = b.dataset.adel;
    if(!confirm(isPetroleum ? "¿Borrar elemento de agenda? Se desactivará para no afectar históricos." : "¿Borrar actividad? Se desactivará para no afectar históricos.")) return;
    await api(`/api/activities/${id}`, {method:"DELETE"});
    toast("Listo", isPetroleum ? "Agenda desactivada." : "Actividad desactivada.");
    await refreshActs();
    calendar?.refetchEvents?.();
  }));
}

async function refreshActs(){
  if (!aT) return;
  const resp = await api("/api/activities");
  actCache = resp.activities || [];
  if (tplCount) tplCount.textContent = String(actCache.length);
  renderTplRows();
}

// -------- Tabs (Calendario / Plantillas) --------
function setupTabs(){
  const tabsEl = qs("#actTabs");
  if (!tabsEl) return;
  const buttons = qsa("#actTabs .tab-btn");
  const panes = qsa("[data-tab-pane]");
  buttons.forEach(btn => btn.addEventListener("click", ()=>{
    const target = btn.dataset.tab;
    buttons.forEach(b => b.classList.toggle("is-active", b === btn));
    panes.forEach(p => { p.hidden = p.dataset.tabPane !== target; });
    if (target === "calendar"){
      // FullCalendar mide alturas al renderizar; al volver de pestaña oculta puede quedar mal.
      try { calendar?.updateSize?.(); } catch(_e){}
    }
  }));
}

if (me?.role==="admin"){
  setupTabs();
  if (btnRefreshActs) btnRefreshActs.addEventListener("click", refreshActs);
  if (tplSearch) tplSearch.addEventListener("input", renderTplRows);
  if (tplStatus) tplStatus.addEventListener("change", renderTplRows);
  if (dlgActEdit){
    dlgActEdit.addEventListener("close", async ()=>{
      // no-op
    });
    qs("#aeSave")?.addEventListener("click", async (e)=>{
      e.preventDefault();
      const id = aeId.value;
      await api(`/api/activities/${id}`, {method:"PUT", body: JSON.stringify({
        title: aeTitle.value,
        description: aeDesc.value,
        evidence_required: aeEvidence.checked,
        is_active: aeActive.checked ? 1 : 0
      })});
      toast("Guardado","Cambios aplicados.");
      dlgActEdit.close();
      await refreshActs();
      calendar?.refetchEvents?.();
    });
  }
  // initial load
  try{ await refreshActs(); }catch(e){}
}
})();