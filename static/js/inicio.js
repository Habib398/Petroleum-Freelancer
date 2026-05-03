/* inicio.js – Scroll Reveal con animación de contadores + formulario de cotización */

/* ── Scroll Reveal + Counter ──────────────────────────────────────────────── */
(function () {
  const targets = document.querySelectorAll('[data-reveal]');
  if (!targets.length || !('IntersectionObserver' in window)) {
    targets.forEach(el => el.classList.add('in-view'));
    return;
  }

  const io = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      const el = entry.target;
      el.classList.add('in-view');

      /* counter animation for stat-value children */
      el.querySelectorAll('[data-counter]').forEach(function (num) {
        animateCounter(num);
      });
      if (el.hasAttribute('data-counter')) animateCounter(el);

      io.unobserve(el);
    });
  }, { threshold: 0.14, rootMargin: '0px 0px -40px 0px' });

  targets.forEach(function (el) { io.observe(el); });

  function animateCounter(el) {
    var target = parseInt(el.getAttribute('data-counter'), 10);
    var suffix = el.getAttribute('data-suffix') || '';
    var delay = parseFloat(window.getComputedStyle(el).transitionDelay) * 1000 || 0;
    var dur = 1100;
    var start = null;

    function easeOutExpo(t) { return t === 1 ? 1 : 1 - Math.pow(2, -10 * t); }

    setTimeout(function () {
      requestAnimationFrame(function tick(ts) {
        if (!start) start = ts;
        var progress = Math.min((ts - start) / dur, 1);
        el.textContent = Math.round(easeOutExpo(progress) * target) + suffix;
        if (progress < 1) requestAnimationFrame(tick);
      });
    }, delay + 200);
  }
})();

/* ── Formulario de cotización ────────────────────────────────────────────── */
(function () {
  const form = document.getElementById('quoteForm');
  const alertBox = document.getElementById('quoteAlert');
  const submitBtn = document.getElementById('quoteSubmit');
  const quoteActions = document.getElementById('quoteActions');
  const quotePdfLink = document.getElementById('quotePdfLink');
  const quoteMeta = document.getElementById('quoteMeta');
  const quotePdfDownloadLink = document.getElementById('quotePdfDownloadLink');
  const csrfMeta = document.querySelector('meta[name="csrf-token"]');
  if (!form || !alertBox || !submitBtn) { return; }

  function hideQuoteResult() {
    if (quoteActions) { quoteActions.classList.remove('show'); }
    if (quoteMeta) {
      quoteMeta.classList.remove('show');
      quoteMeta.textContent = '';
    }
    if (quotePdfLink) { quotePdfLink.setAttribute('href', '#'); }
    if (quotePdfDownloadLink) { quotePdfDownloadLink.setAttribute('href', '#'); }
  }

  function showAlert(kind, message) {
    alertBox.className = 'quote-alert show ' + kind;
    alertBox.textContent = message;
  }

  form.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    submitBtn.disabled = true;
    hideQuoteResult();
    showAlert('warn', 'Enviando solicitud...');
    try {
      const formData = new FormData(form);
      const response = await fetch('/api/public/quote-request', {
        method: 'POST',
        headers: {
          'X-CSRF-Token': formData.get('csrf_token') || (csrfMeta ? csrfMeta.getAttribute('content') : ''),
          'Accept': 'application/json'
        },
        body: formData,
        credentials: 'same-origin'
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        showAlert('error', data.message || 'No se pudo enviar la cotización. Revisa los campos e inténtalo de nuevo.');
        return;
      }
      if (data.status === 'sent') {
        showAlert('ok', 'Tu solicitud fue enviada correctamente. Ya puedes abrir o descargar la propuesta preliminar en PDF.');
      } else {
        showAlert('warn', 'Tu solicitud quedó registrada y la propuesta preliminar en PDF ya está lista. El envío automático por correo depende de la configuración del servidor.');
      }
      if (data.folio && quoteMeta) {
        quoteMeta.classList.add('show');
        quoteMeta.textContent = 'Folio generado: ' + data.folio;
      }
      if (data.pdf_url && quotePdfLink && quoteActions) {
        quotePdfLink.setAttribute('href', data.pdf_url);
        if (quotePdfDownloadLink) {
          quotePdfDownloadLink.setAttribute('href', data.pdf_url + (data.pdf_url.includes('?') ? '&' : '?') + 'download=1');
        }
        quoteActions.classList.add('show');
        window.open(data.pdf_url, '_blank', 'noopener');
      }
      form.reset();
    } catch (err) {
      showAlert('error', 'Ocurrió un problema al enviar la solicitud. Inténtalo nuevamente.');
    } finally {
      submitBtn.disabled = false;
    }
  });
})();
