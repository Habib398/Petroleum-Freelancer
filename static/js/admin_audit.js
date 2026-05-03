async function load(q=""){
  const r = await api("/api/admin/audit"+(q?("?q="+encodeURIComponent(q)):""));
  const tb = qs("#aT");
  tb.innerHTML = (r.audit||[]).map(a=>`
    <tr>
      <td>${(a.created_at||"").slice(0,19).replace("T"," ")}</td>
      <td>${a.actor_user_id||"—"}</td>
      <td><b>${a.action}</b></td>
      <td>${a.entity||""} <span class="muted">${a.entity_id||""}</span></td>
      <td class="muted" style="max-width:520px;white-space:pre-wrap;">${(a.meta_json||"").slice(0,220)}</td>
    </tr>
  `).join("");
}
document.addEventListener("DOMContentLoaded", ()=>{
  qs("#abtn").addEventListener("click", ()=> load(qs("#aq").value));
  load();
});
