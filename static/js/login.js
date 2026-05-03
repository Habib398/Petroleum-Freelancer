/* login.js – Lógica de la pantalla de inicio de sesión */

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  try{
    const meta = document.querySelector('meta[name="csrf-token"]');
    const token = meta ? meta.getAttribute('content') : "";
    if (token) headers["X-CSRF-Token"] = token;
  }catch(e){}
  headers["Content-Type"] = "application/json";
  const res = await fetch(path, { credentials: "include", ...opts, headers });
  const data = await res.json().catch(()=> ({}));
  if (!res.ok) throw new Error(data.error || "http_"+res.status);
  return data;
}

const err = document.getElementById("err");
const btn = document.getElementById("btn");
const form = document.getElementById("loginForm");
const togglePw = document.getElementById("togglePw");
const inputPw = document.getElementById("p");

togglePw.addEventListener("click", () => {
  const isPw = inputPw.type === "password";
  inputPw.type = isPw ? "text" : "password";
  togglePw.textContent = isPw ? "Ocultar" : "Mostrar";
});

async function doLogin(){
  err.classList.remove("show");
  err.textContent = "";
  btn.disabled = true;
  const originalHtml = btn.innerHTML;
  btn.innerHTML = '<span>Verificando...</span>';
  try{
    await api("/api/auth/login",{method:"POST",body:JSON.stringify({username:document.getElementById("u").value,password:document.getElementById("p").value})});
    const me = await api("/api/me");
    const role = (me && me.me && me.me.role) ? me.me.role : "";
    const allowed = (me && me.me && me.me.allowed_brands) ? me.me.allowed_brands : "";
    if(role==="admin" || (allowed && allowed.includes(","))){
      location.href="/select-system";
    }else{
      let brand = "consulting";
      if(allowed && allowed.trim().length){
        brand = allowed.trim().toLowerCase();
      }
      try{
        await api("/api/set-brand",{method:"POST",body:JSON.stringify({brand})});
      }catch(_e){}
      location.href = (role==="admin") ? "/admin/menu" : "/staff/menu";
    }
  }catch(e){
    err.textContent = "No se pudo iniciar sesión: " + e.message;
    err.classList.add("show");
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
}

form.addEventListener("submit", (ev)=>{
  ev.preventDefault();
  doLogin();
});
