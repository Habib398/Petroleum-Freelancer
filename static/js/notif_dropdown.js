(async () => {
  const notifBtn = qs('#notifBtn');
  const notifPopup = qs('#notifPopup');
  const notifContent = qs('#notifContent');
  const notifBadge = qs('#notifBadge');

  if (!notifBtn || !notifPopup) return;

  async function updateUnreadCount() {
    try {
      const data = await api('/api/notifications/unread-count');
      const count = data.unread || 0;

      if (notifBadge) {
        if (count > 0) {
          notifBadge.textContent = count;
          notifBadge.style.display = 'inline-block';
          // Agregar badge visual al botón también
          let badgeInBtn = notifBtn.querySelector('.notif-badge-btn');
          if (!badgeInBtn) {
            badgeInBtn = document.createElement('span');
            badgeInBtn.className = 'notif-badge-btn';
            badgeInBtn.textContent = count;
            notifBtn.appendChild(badgeInBtn);
          } else {
            badgeInBtn.textContent = count;
          }
        } else {
          notifBadge.style.display = 'none';
          const badgeInBtn = notifBtn.querySelector('.notif-badge-btn');
          if (badgeInBtn) badgeInBtn.remove();
        }
      }
    } catch (e) {
      console.error('Error loading unread count:', e);
    }
  }

  async function loadNotifications() {
    try {
      const data = await api('/api/notifications?limit=5');
      const items = data.notifications || [];

      if (!items.length) {
        notifContent.innerHTML = '<div style="padding:20px;text-align:center;color:var(--hme-text-soft);font-size:13px;">Sin notificaciones nuevas</div>';
        return;
      }

      notifContent.innerHTML = items.map(n => {
        const isRead = !!n.is_read;
        const title = _esc(n.title || 'Notificación');
        const body = _esc(n.body || '');
        const when = (n.created_at || '').replace('T', ' ').slice(0, 16);
        const url = String(n.url || '');

        return `
          <div class="notif-item ${isRead ? 'notif-read' : 'notif-unread'}">
            <div class="notif-indicator"></div>
            <div class="notif-body" style="flex:1;min-width:0;">
              <div class="notif-title">${title}</div>
              ${body ? `<div class="notif-desc">${body}</div>` : ''}
              <div class="notif-time">${when}</div>
            </div>
            ${url ? `<a class="btn small" href="${url}" style="flex:0 0 auto;">Abrir</a>` : ''}
          </div>
        `;
      }).join('');
      
      // Actualizar contador cuando se abre el popup
      await updateUnreadCount();
    } catch (e) {
      notifContent.innerHTML = '<div style="padding:20px;text-align:center;color:var(--hme-danger);font-size:13px;">Error al cargar notificaciones</div>';
    }
  }

  // Cargar notificaciones al hacer click
  notifBtn.addEventListener('click', async (e) => {
    e.stopPropagation();
    const isHidden = notifPopup.hasAttribute('hidden');

    if (isHidden) {
      notifPopup.removeAttribute('hidden');
      await loadNotifications();
    } else {
      notifPopup.setAttribute('hidden', '');
    }
  });

  // Cerrar al hacer click fuera
  document.addEventListener('click', (e) => {
    if (!qs('#notifDropdown').contains(e.target)) {
      notifPopup.setAttribute('hidden', '');
    }
  });

  // Cargar contador al inicializar
  await updateUnreadCount();

  // Cargar notificaciones cada 30 segundos
  setInterval(async () => {
    await updateUnreadCount();
    // Si el popup está abierto, actualizar también las notificaciones
    if (!notifPopup.hasAttribute('hidden')) {
      await loadNotifications();
    }
  }, 30000);
})();
