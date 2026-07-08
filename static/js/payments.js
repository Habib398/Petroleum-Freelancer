(async ()=>{
  let me; try{ me=(await api("/api/me")).me; }catch(e){return;}
  const tb = qs("#payT");
  const err = qs("#payErr");

  // --- Control de acceso a campos de fecha (periodo) ---
  // Solo admin y contador pueden modificar el periodo de facturación.
  // El resto de roles (jefe_estacion, operador, etc.) ve los campos bloqueados.
  const CAN_EDIT_PERIOD = me && (me.role === "admin" || me.role === "contador");
  const periodInputs = [qs("#payPeriodStart"), qs("#payPeriodEnd")];
  periodInputs.forEach(input => {
    if (!input) return;
    if (CAN_EDIT_PERIOD) {
      input.removeAttribute("readonly");
      input.style.removeProperty("background");
      input.style.removeProperty("color");
      input.style.removeProperty("cursor");
      input.style.removeProperty("pointer-events");
      input.title = "";
    } else {
      input.title = "Solo el administrador o contador puede modificar las fechas de periodo.";
    }
  });



  function fileLink(rel){
    if(!rel) return '<span class="muted">—</span>';
    return `<a href="/uploads/${rel}">Descargar</a>`;
  }
  async function refresh(){
    const rows = (await api("/api/payments")).payments || [];
    tb.innerHTML = rows.map(r=>`
      <tr>
        <td>${r.id}</td>
        <td>${(r.created_at||"").slice(0,10)}</td>
        <td>${r.station_name||""}</td>
        <td>${r.status==="pending"?'<span class="pill yellow">Pendiente</span>':r.status==="validated"?'<span class="pill green">Validado</span>':'<span class="pill red">Rechazado</span>'}</td>
        <td>${fileLink(r.proof_path)}</td>
        <td>${fileLink(r.invoice_path)}</td>
      </tr>
    `).join("");
  }

  qs("#payProof").addEventListener("submit", async (ev)=>{
    ev.preventDefault();
    err.hidden=true;
    try{
      const fd = new FormData(ev.target);
      await api("/api/payments/proof",{method:"POST",body:fd,headers:{}});
      toast("Enviado","Comprobante enviado para revisión.");
      ev.target.reset();
      await refresh();
    }catch(e){
      err.textContent="Error: "+e.message;
      err.hidden=false;
    }
  });

  const rv = qs("#payReview");
  if (rv){
    rv.addEventListener("submit", async (ev)=>{
      ev.preventDefault();
      const fd = new FormData(ev.target);
      const id = fd.get("payment_id");
      await api(`/api/payments/${id}/review`,{method:"POST",body:fd,headers:{}});
      toast("Listo","Revisión aplicada.");
      ev.target.reset();
      await refresh();
    });
  }

  await refresh();
})();
