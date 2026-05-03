
(function(){
  const CFG = {
    consultingName: "HME Consulting",
    petroleumName: "HME Petroleum",
    // Cambia estas URLs por las oficiales cuando las tengas:
    consultingUrl: "https://consultinghme.com/",
    petroleumUrl: "https://petroleumiu.com/",
    contactText: "Si necesitas acceso, pide al administrador que te cree un usuario (Operador / Jefe de estación / Auditor).",
    consultingDesc: "Empresa enfocada en consultoría, gestión y seguimiento operativo con control documental y evidencias.",
    petroleumDesc: "Empresa enfocada en operación de estación/energía con control de pipas, mantenimientos y cumplimiento."
  };

  const qs = (s, el=document)=>el.querySelector(s);

  const fab = qs('#chatbotFab');
  const panel = qs('#chatbotPanel');
  const closeBtn = qs('#chatbotClose');
  const body = qs('#chatbotBody');
  const input = qs('#chatbotInput');
  const send = qs('#chatbotSend');

  function escapeHtml(str){
    return str.replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
  }

  function addMsg(who, title, html){
    const div = document.createElement('div');
    div.className = 'chatbot-msg ' + (who==='user' ? 'user' : 'bot');
    div.innerHTML = `<div class="meta">${escapeHtml(title)}</div><div class="text">${html}</div>`;
    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
  }

  function open(){
    panel.classList.add('open');
    fab.setAttribute('aria-expanded','true');
    input && input.focus();
  }
  function close(){
    panel.classList.remove('open');
    fab.setAttribute('aria-expanded','false');
  }

  function toggle(){
    if(panel.classList.contains('open')) close(); else open();
  }

  function answer(text){
    const t = text.toLowerCase().trim();

    if(t.includes('consult') || t.includes('consulting')){
      addMsg('bot', CFG.consultingName, `
        <div>${escapeHtml(CFG.consultingDesc)}</div>
        <div style="margin-top:10px;">Sitio oficial: <a class="chatbot-link" href="${CFG.consultingUrl}" target="_blank" rel="noopener">Abrir</a></div>
      `);
      return;
    }
    if(t.includes('petro') || t.includes('petroleum')){
      addMsg('bot', CFG.petroleumName, `
        <div>${escapeHtml(CFG.petroleumDesc)}</div>
        <div style="margin-top:10px;">Sitio oficial: <a class="chatbot-link" href="${CFG.petroleumUrl}" target="_blank" rel="noopener">Abrir</a></div>
      `);
      return;
    }
    if(t.includes('usuario') || t.includes('acceso') || t.includes('login') || t.includes('cuenta')){
      addMsg('bot', 'Acceso', `<div>${escapeHtml(CFG.contactText)}</div>`);
      return;
    }
    if(t.includes('sitio') || t.includes('pagina') || t.includes('oficial') || t.includes('web')){
      addMsg('bot', 'Páginas oficiales', `
        <div style="display:grid; gap:8px; margin-top:6px;">
          <div>• ${escapeHtml(CFG.consultingName)}: <a class="chatbot-link" href="${CFG.consultingUrl}" target="_blank" rel="noopener">Abrir</a></div>
          <div>• ${escapeHtml(CFG.petroleumName)}: <a class="chatbot-link" href="${CFG.petroleumUrl}" target="_blank" rel="noopener">Abrir</a></div>
        </div>
      `);
      return;
    }

    addMsg('bot','Ayuda', `
      <div>Puedo contarte sobre las 2 empresas o ayudarte con el acceso.</div>
      <div style="margin-top:10px;" class="chatbot-quick">
        <button class="chatbot-chip consulting" data-q="¿Qué es Consulting?">¿Qué es Consulting?</button>
        <button class="chatbot-chip petroleum" data-q="¿Qué es Petroleum?">¿Qué es Petroleum?</button>
        <button class="chatbot-chip" data-q="Necesito acceso / usuario">Necesito usuario</button>
        <button class="chatbot-chip" data-q="Páginas oficiales">Páginas oficiales</button>
      </div>
    `);
  }

  function sendText(){
    const text = (input.value || '').trim();
    if(!text) return;
    addMsg('user','Tú', `<div>${escapeHtml(text)}</div>`);
    input.value = '';
    // simulate quick response
    window.setTimeout(()=>answer(text), 120);
  }

  // wire
  if(fab){
    fab.addEventListener('click', toggle);
  }
  if(closeBtn){
    closeBtn.addEventListener('click', close);
  }
  if(send){
    send.addEventListener('click', sendText);
  }
  if(input){
    input.addEventListener('keydown', (e)=>{
      if(e.key === 'Enter'){ e.preventDefault(); sendText(); }
      if(e.key === 'Escape'){ close(); }
    });
  }
  document.addEventListener('click', (e)=>{
    const btn = e.target.closest && e.target.closest('.chatbot-chip');
    if(btn){
      const q = btn.getAttribute('data-q') || btn.textContent;
      addMsg('user','Tú', `<div>${escapeHtml(q)}</div>`);
      window.setTimeout(()=>answer(q), 120);
    }
  });

  // initial greeting (only once per tab)
  try{
    const key='hme_chatbot_greeted';
    if(!sessionStorage.getItem(key)){
      sessionStorage.setItem(key,'1');
      addMsg('bot','Asistente', `
        <div>Hola 👋 Puedo explicarte qué es <b>${escapeHtml(CFG.consultingName)}</b> y <b>${escapeHtml(CFG.petroleumName)}</b>, y darte sus páginas oficiales.</div>
        <div class="chatbot-quick" style="margin-top:10px;">
          <button class="chatbot-chip consulting" data-q="¿Qué es Consulting?">Consulting</button>
          <button class="chatbot-chip petroleum" data-q="¿Qué es Petroleum?">Petroleum</button>
          <button class="chatbot-chip" data-q="Páginas oficiales">Páginas oficiales</button>
          <button class="chatbot-chip" data-q="Necesito acceso / usuario">Necesito usuario</button>
        </div>
      `);
    }
  }catch(err){}
})();
