async function api(path, opts = {}) {
  const headers = opts.headers || {};
  // CSRF token injected by server into templates
  try{
    const meta = document.querySelector('meta[name="csrf-token"]');
    const token = meta ? meta.getAttribute('content') : "";
    if (token) headers["X-CSRF-Token"] = token;
  }catch(e){}
  if (!(opts.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(path, { credentials: "include", ...opts, headers });
  let data = null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) data = await res.json();
  else data = await res.text();
  if (!res.ok) {
    const err = (data && data.error) ? data.error : ("http_" + res.status);
    throw new Error(err);
  }
  return data;
}

function qs(sel, el=document){ return el.querySelector(sel); }
function qsa(sel, el=document){ return Array.from(el.querySelectorAll(sel)); }

function _esc(v){
  return String(v ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}


function toast(title, body=""){
  const el = qs("#toast");
  if (!el) return;
  qs(".t", el).textContent = title;
  qs(".b", el).textContent = body;
  el.classList.add("show");
  setTimeout(()=> el.classList.remove("show"), 3600);
}

async function loadMe(){
  const r = await api("/api/me");
  const me = r.me;
  const u = qs("#me-name");
  if (u) u.textContent = me.username + " • " + me.role;
  // admin links visibility
  qsa("[data-admin-only]").forEach(a=>{
    a.hidden = me.role !== "admin";
  });
  // not-operador links (hide for operador)
  qsa("[data-not-operador]").forEach(a=>{
    a.hidden = me.role === "operador";
  });
  // not-admin links (hide for admin: admin tiene su propia entrada)
  qsa("[data-not-admin]").forEach(a=>{
    a.hidden = me.role === "admin";
  });

  // Classroom: el calendario de actividades es solo del operador.
  qsa("[data-operador-only]").forEach(a=>{
    a.hidden = me.role !== "operador";
  });
  // Supervisores (admin/jefe): calendario operativo.
  qsa("[data-supervisor-only]").forEach(a=>{
    a.hidden = !["admin","jefe_estacion"].includes(me.role);
  });
  // Solo jefe de estación (no admin): evidencias por estación en operación.
  qsa("[data-jefe-only]").forEach(a=>{
    a.hidden = me.role !== "jefe_estacion";
  });

  // privileged-only links (admin/contador/auditor)
  qsa("[data-map-privileged]").forEach(a=>{
    a.hidden = !["admin","contador","auditor"].includes(me.role);
  });
  qsa("[data-admin-auditor-only]").forEach(a=>{
    a.hidden = !["admin","auditor"].includes(me.role);
  });
  // station blocked banner
  const blocked = (me.role !== "admin") && (me.monthly_status === "view_only" || me.monthly_status === "expired");
  const banner = qs("#blocked-banner");
  if (banner) banner.hidden = !blocked;
  return me;
}


function renderRoleGuide(me){
  const titleEl = qs("#roleGuideTitle");
  const textEl = qs("#roleGuideText");
  const stepsEl = qs("#roleGuideSteps");
  if (!titleEl || !textEl || !stepsEl || !me) return;
  const brand = document.body.classList.contains("brand-petroleum") ? "petroleum" : "consulting";
  let title = "Qué hacer primero";
  let text = "Usa estos accesos para entrar al módulo correcto sin perderte.";
  let steps = [];
  if (me.role === "admin"){
    title = brand === "petroleum" ? "Admin Petroleum" : "Admin Consulting";
    text = brand === "petroleum"
      ? "Primero revisa normativas y vencimientos; después entra al control maestro para supervisión global."
      : "Primero revisa SASISOPA/SGM y después el centro documental para seguimiento por estación.";
    steps = brand === "petroleum"
      ? ["Normativas: captura y controla registros técnicos.", "Expediente normativo: carpeta completa por estación.", "Control maestro: tabla global para revisar vencidos y renovaciones."]
      : ["SASISOPA: programación y documentos controlados.", "SGM: gestión y seguimiento documental.", "Centro documental: consulta y revisión global por estación."];
  } else if (["jefe_estacion","operador"].includes(me.role)){
    title = brand === "petroleum" ? "Tu operación en Petroleum" : "Tu operación en Consulting";
    text = brand === "petroleum"
      ? "Entra primero a normativas para subir documentos y luego revisa faltantes y vencimientos."
      : "Consulta primero los módulos documentales asignados por el administrador y luego revisa tus avisos.";
    steps = brand === "petroleum"
      ? ["Normativas: sube o actualiza documentos de tu estación.", "Expediente normativo: revisa faltantes y porcentaje.", "Vencimientos: mira qué se renueva pronto."]
      : ["SASISOPA / SGM: consulta documentos recibidos y edita solo campos liberados.", "Documentos de estación: revisa carpeta compartida según tu alcance.", "Notificaciones: revisa avisos y pendientes."];
  } else {
    title = "Panel global";
    text = "Si tu usuario no tiene estación fija, puedes recorrer todas las estaciones del sistema activo según tu rol.";
    steps = ["Dashboard: resumen general.", "Mapa / estaciones: vista global de cobertura.", "Carpeta compartida y documentos: consulta por estación."];
  }
  titleEl.textContent = title;
  textEl.textContent = text;
  stepsEl.innerHTML = steps.map((s,i)=>`<div class="role-guide-step"><b>${i+1}</b><span>${_esc(s)}</span></div>`).join("");
}

function setActiveNav(){
  const path = location.pathname;
  qsa(".nav a").forEach(a=>{
    const isActive = a.getAttribute("href") === path;
    a.classList.toggle("active", isActive);
    // If this link is active, open its parent details element
    if (isActive){
      let parent = a.closest("details");
      if (parent) parent.open = true;
    }
  });
}

function initTheme(){
  const saved = localStorage.getItem("cog-theme") || "light";
  document.body.classList.toggle("dark", saved === "dark");
  const btn = qs("#theme-toggle");
  if (btn){
    btn.addEventListener("click", ()=>{
      const nowDark = !document.body.classList.contains("dark");
      document.body.classList.toggle("dark", nowDark);
      localStorage.setItem("cog-theme", nowDark ? "dark":"light");
    });
  }
}

function initNavToggle(){
  const btn = qs("#nav-toggle");
  const sidebar = qs(".sidebar");
  if (!btn || !sidebar) return;

  const sync = ()=>{
    const isOpen = document.body.classList.contains("nav-open");
    btn.setAttribute("aria-expanded", isOpen ? "true" : "false");
  };

  btn.addEventListener("click", ()=>{
    document.body.classList.toggle("nav-open");
    sync();
  });

  document.addEventListener("click", (e)=>{
    if (!document.body.classList.contains("nav-open")) return;
    if (e.target === btn) return;
    if (!sidebar.contains(e.target)) {
      document.body.classList.remove("nav-open");
      sync();
    }
  });

  document.addEventListener("keydown", (e)=>{
    if (e.key === "Escape" && document.body.classList.contains("nav-open")){
      document.body.classList.remove("nav-open");
      sync();
    }
  });

  qsa(".sidebar a").forEach((link)=>{
    link.addEventListener("click", ()=>{
      if (window.innerWidth <= 980){
        document.body.classList.remove("nav-open");
        sync();
      }
    });
  });

  window.addEventListener("resize", ()=>{
    if (window.innerWidth > 980 && document.body.classList.contains("nav-open")){
      document.body.classList.remove("nav-open");
      sync();
    }
  });

  sync();
}


function getNotifLastSeenKey(){
  // per-user if possible
  const uname = (qs("#me-name") && qs("#me-name").textContent) ? qs("#me-name").textContent.split("•")[0].trim() : "";
  return "notif_last_seen_id::" + (uname || "anon");
}

async function fetchNotifications(limit=20){
  // returns array or []
  const data = await api(`/api/notifications?limit=${encodeURIComponent(limit)}`);
  return data.notifications || [];
}

async function fetchUnreadCount(){
  const data = await api("/api/notifications/unread-count");
  return parseInt(data.unread ?? 0, 10) || 0;
}

function updateNotifBadges(unread){
  const badge = qs("#notifBadge");
  const dot = qs("#notifDot");
  if (badge){
    if (unread>0){
      badge.textContent = unread>99 ? "99+" : String(unread);
      badge.style.display = "inline-flex";
    } else {
      badge.style.display = "none";
    }
  }
  if (dot){
    if (unread>0){
      dot.textContent = unread>99 ? "99+" : String(unread);
      dot.style.display = "grid";
    } else {
      dot.style.display = "none";
    }
  }
}

async function fetchIncidentsPending(){
  try {
    const data = await api("/api/incidents/pending-count");
    return parseInt(data.count ?? 0, 10) || 0;
  } catch(e){ return 0; }
}

function updateIncidentsBadge(count){
  const badge = qs("#incidentsBadge");
  if (!badge) return;
  if (count > 0){
    badge.textContent = count > 99 ? "99+" : String(count);
    badge.style.display = "inline-flex";
  } else {
    badge.style.display = "none";
  }
}

function initIncidentsBadge(me){
  // El badge solo aplica al jefe de estación: refleja su obligación
  // de marcar incidencias pendientes en su scope.
  if (!me || me.role !== "jefe_estacion") return;
  async function tick(){
    const n = await fetchIncidentsPending();
    updateIncidentsBadge(n);
  }
  tick();
  setInterval(tick, 30000);
}

function initNotifications(){
  // Poll in-app notifications and show badge + optional toast
  let lastToastId = 0;
  const key = getNotifLastSeenKey();
  const lastSeen = parseInt(localStorage.getItem(key) || "0", 10) || 0;

  async function tick(){
    try{
      const unread = await fetchUnreadCount();
      updateNotifBadges(unread);

      const items = await fetchNotifications(10);
      if (!items.length) return;

      const newestId = items[0].id || 0;
      // Initialize lastToastId once
      if (!lastToastId) lastToastId = lastSeen;

      // Toast only if new notifications arrived
      if (newestId > lastToastId){
        const newOnes = items.filter(n => (n.id||0) > lastToastId);
        // show toast for the most recent
        const n = newOnes[0] || items[0];
        if (location.pathname !== "/mod/notifications"){
          toast(n.title || "Nueva notificación", n.body || "");
        }
        lastToastId = newestId;
        // do not auto-mark read; only remember we've shown toast
        localStorage.setItem(key, String(newestId));
      }
    }catch(e){
      // silent
    }
  }

  tick();
  setInterval(tick, 20000);
}


document.addEventListener("DOMContentLoaded", async ()=>{
  initTheme();
  initNavToggle();
  let __me = null;
  try{
    __me = await loadMe();
    try{ renderRoleGuide(__me); }catch(e){}
  }catch(e){
    // if not authenticated, allow on login/inicio
  }
  setActiveNav();
  try{ initNotifications(); }catch(e){}
  try{ initIncidentsBadge(__me); }catch(e){}
});
