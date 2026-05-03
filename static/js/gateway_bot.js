/* gateway_bot.js - Lógica del chatbot informativo de la pantalla de bienvenida */

(() => {
  const openBot = document.getElementById('openBot');
  const closeBot = document.getElementById('closeBot');
  const bot = document.getElementById('bot');
  const body = document.getElementById('botBody');
  const form = document.getElementById('botForm');
  const input = document.getElementById('botInput');
  const chips = document.getElementById('botChips');

  // Recuperar configuración (inyectada en el HTML por Jinja2) o usar valores por defecto
  const config = window.GatewayConfig || {
    consultingUrl: 'https://consultinghme.com/',
    partnerUrl: 'https://petroleumiu.com/'
  };

  const QUICK = [
    '¿A qué se dedica Consulting?',
    'Servicios principales',
    '¿Cómo entro al sistema?',
    'Sitio oficial Consulting',
    'Sitio oficial Petroleum',
    'Contacto'
  ];

  const KB = [
    { keys: ['a que se dedica', 'que hace consulting', 'consulting a que se dedica'],
      answer: `Consulting Oil & Gas (Renewable Energy HME) ofrece servicios de consultoría y soluciones en el sector energético, con enfoque en gestión, cumplimiento y soporte operativo. Para más información visita el sitio oficial: ${config.consultingUrl}` },
    { keys: ['servicios', 'servicios principales', 'que servicios'],
      answer: `Servicios típicos: consultoría técnica/operativa, soporte a procesos y seguimiento de actividades (bitácoras, evidencias y cumplimiento). Este chat es informativo; para detalles completos consulta: ${config.consultingUrl}` },
    { keys: ['entrar', 'login', 'iniciar sesion', 'como entro al sistema'],
      answer: 'Para entrar al sistema da clic en el panel de Consulting (lado izquierdo). Te enviará al inicio de sesión.' },
    { keys: ['sitio oficial consulting', 'web consulting', 'pagina consulting'],
      answer: `Sitio oficial de Consulting: ${config.consultingUrl}` },
    { keys: ['sitio official petroleum', 'sitio oficial petroleum', 'web petroleum', 'pagina petroleum'],
      answer: `Sitio oficial de Petroleum (Oil & Gas Inspection Unit): ${config.partnerUrl}` },
    { keys: ['contacto', 'correo', 'telefono', 'ubicacion'],
      answer: `Para información de contacto, consulta los apartados de contacto en los sitios oficiales: ${config.consultingUrl} y ${config.partnerUrl}` },
  ];

  const normalize = (s) => (s||'').toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g,'')
    .replace(/[^a-z0-9\s&?]/g,' ')
    .replace(/\s+/g,' ').trim();

  function show(on) {
    if (!bot) return;
    bot.classList.toggle('is-open', !!on);
    bot.setAttribute('aria-hidden', on ? 'false' : 'true');
    if (on) setTimeout(() => input?.focus(), 50);
  }

  function addMsg(who, text) {
    const row = document.createElement('div');
    row.className = 'bot__row ' + (who === 'me' ? 'bot__row--me' : 'bot__row--bot');
    const bubble = document.createElement('div');
    bubble.className = 'bot__bubble';
    bubble.textContent = text;
    row.appendChild(bubble);
    body.appendChild(row);
    body.scrollTop = body.scrollHeight;
  }

  function answer(q) {
    const nq = normalize(q);
    const hit = KB.find(it => it.keys.some(k => nq.includes(normalize(k))));
    if (hit) return addMsg('bot', hit.answer);
    addMsg('bot', 'Puedo ayudarte con: servicios, cómo entrar al sistema, y enlaces oficiales. Usa una pregunta rápida 👇');
  }

  function renderChips() {
    QUICK.forEach(t => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'bot__chip';
      b.textContent = t;
      b.addEventListener('click', () => { addMsg('me', t); answer(t); });
      chips.appendChild(b);
    });
  }

  openBot?.addEventListener('click', () => show(true));
  closeBot?.addEventListener('click', () => show(false));
  bot?.addEventListener('click', (e) => { if (e.target === bot) show(false); });

  form?.addEventListener('submit', (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) return;
    addMsg('me', q);
    input.value = '';
    answer(q);
  });

  renderChips();
  addMsg('bot', 'Hola 👋 Soy un chat informativo. ¿Qué te gustaría saber?');
})();
