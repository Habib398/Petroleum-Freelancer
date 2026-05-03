(async ()=>{
  let me; try{ me=(await api("/api/me")).me; }catch(e){return;}
  const tb = qs("#payT");
  const err = qs("#payErr");

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
