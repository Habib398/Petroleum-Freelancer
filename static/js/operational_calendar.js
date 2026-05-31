(async () => {
  const fromEl = qs('#dFrom');
  const toEl = qs('#dTo');
  const tplStripEl = qs('#opcalTplStrip');
  const tplListEl = qs('#opcalTplList');
  const tplCountEl = qs('#opcalTplCount');
  const chipsEl = qs('#opcalChips');
  const viewsEl = qs('#opcalViews');
  const popoverEl = qs('#opcalPopover');
  const popoverBackdropEl = qs('#opcalPopoverBackdrop');

  const today = new Date();
  const first = new Date(today.getFullYear(), today.getMonth(), 1);
  const last = new Date(today.getFullYear(), today.getMonth() + 1, 0);
  fromEl.value = first.toISOString().slice(0, 10);
  toEl.value = last.toISOString().slice(0, 10);

  const enabledKinds = new Set(['actividad', 'documento', 'vencimiento', 'cumplimiento']);
  let lastItems = [];
  let lastTemplates = [];

  const KIND_COLOR = {
    actividad: '#2563eb',
    documento: '#7c3aed',
    vencimiento: '#ea580c',
    cumplimiento: '#dc2626',
    plantilla: '#0d9488',
  };
  const KIND_LABEL = {
    actividad: 'Actividad / agenda',
    documento: 'Documento',
    vencimiento: 'Vencimiento de documento',
    cumplimiento: 'Cumplimiento normativo',
    plantilla: 'Plantilla del mes',
  };
  const STATUS_LABEL = {
    open: 'Abierto', pending: 'Pendiente', submitted: 'Entregado',
    approved: 'Aprobado', rejected: 'Rechazado', closed: 'Cerrado',
  };

  function fmtDate(s) {
    if (!s) return '';
    try {
      const d = new Date(s + 'T00:00:00');
      return d.toLocaleDateString('es-MX', { day: '2-digit', month: 'long', year: 'numeric' });
    } catch (e) { return s; }
  }

  const cal = new FullCalendar.Calendar(qs('#calendar'), {
    initialView: 'dayGridMonth',
    locale: 'es',
    height: 720,
    firstDay: 1,
    dayMaxEvents: 3,
    moreLinkText: (n) => `+ ${n} más`,
    fixedWeekCount: false,
    headerToolbar: { left: 'prev,next today', center: 'title', right: '' },
    buttonText: { today: 'Hoy' },
    eventDisplay: 'block',
    eventClick(info) {
      info.jsEvent.preventDefault();
      openPopover({
        title: info.event.extendedProps.rawTitle || info.event.title,
        kind: info.event.extendedProps.kind,
        date: info.event.extendedProps.itemDate,
        end_date: info.event.extendedProps.itemEnd,
        station_name: info.event.extendedProps.station_name,
        status: info.event.extendedProps.status,
        module: info.event.extendedProps.module,
        overdue: info.event.extendedProps.overdue,
        color: info.event.backgroundColor,
      });
    },
    events: [],
  });
  cal.render();

  viewsEl.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-view]');
    if (!btn) return;
    viewsEl.querySelectorAll('button').forEach(b => b.classList.toggle('active', b === btn));
    cal.changeView(btn.dataset.view);
  });

  chipsEl.addEventListener('click', (e) => {
    const chip = e.target.closest('.cal-chip');
    if (!chip) return;
    const kind = chip.dataset.kind;
    if (enabledKinds.has(kind)) {
      enabledKinds.delete(kind); chip.classList.remove('on'); chip.classList.add('off');
    } else {
      enabledKinds.add(kind); chip.classList.add('on'); chip.classList.remove('off');
    }
    renderEvents();
  });

  function renderEvents() {
    cal.removeAllEvents();
    const visible = lastItems.filter(it => enabledKinds.has(it.kind));
    visible.forEach(it => {
      let endVal;
      if (it.end_date && it.end_date !== it.date) {
        try {
          const d = new Date(it.end_date + 'T00:00:00');
          d.setDate(d.getDate() + 1);
          endVal = d.toISOString().slice(0, 10);
        } catch (e) {}
      }
      cal.addEvent({
        title: (it.overdue ? '⚠ ' : '') + it.title,
        start: it.date,
        end: endVal,
        color: it.color || KIND_COLOR[it.kind] || '#64748b',
        classNames: it.overdue ? ['is-overdue'] : [],
        extendedProps: {
          kind: it.kind,
          rawTitle: it.title,
          itemDate: it.date,
          itemEnd: it.end_date,
          station_name: it.station_name,
          status: it.status,
          module: it.module,
          overdue: !!it.overdue,
        },
      });
    });
  }

  function renderTemplates(templates) {
    const list = templates || [];
    if (!list.length) {
      tplStripEl.classList.remove('show');
      tplListEl.innerHTML = '';
      tplCountEl.textContent = '0';
      return;
    }
    tplStripEl.classList.add('show');
    tplCountEl.textContent = String(list.length);
    tplListEl.innerHTML = list.map((t, idx) => {
      const name = _esc(t.name || '');
      const mod = _esc(t.module || '');
      const ft = _esc(t.file_type || '');
      const cls = t.overdue ? 'opcal-tplchip is-overdue' : 'opcal-tplchip';
      const warn = t.overdue ? '<span class="warn" aria-label="Vencida">⚠</span>' : '';
      return `<button type="button" class="${cls}" data-tpl-idx="${idx}">
        ${warn}
        <span class="mod">${mod}</span>
        <span>${name}</span>
        ${ft ? `<span class="ft">${ft}</span>` : ''}
      </button>`;
    }).join('');
  }

  tplListEl.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-tpl-idx]');
    if (!btn) return;
    const t = lastTemplates[parseInt(btn.dataset.tplIdx, 10)];
    if (!t) return;
    openPopover({
      title: t.name,
      kind: 'plantilla',
      date: t.month_start,
      end_date: t.month_end,
      station_name: 'Todas las estaciones',
      module: t.module,
      file_type: t.file_type,
      description: t.description,
      overdue: !!t.overdue,
      color: KIND_COLOR.plantilla,
    });
  });

  function updateChipCounts(items) {
    const counts = { actividad: 0, documento: 0, vencimiento: 0, cumplimiento: 0 };
    items.forEach(it => { if (counts[it.kind] !== undefined) counts[it.kind]++; });
    Object.keys(counts).forEach(k => {
      const el = chipsEl.querySelector(`[data-c="${k}"]`);
      if (el) el.textContent = String(counts[k]);
    });
  }

  // ===== Popover de detalle =====
  function openPopover(d) {
    const color = d.color || KIND_COLOR[d.kind] || '#64748b';
    const kindLabel = KIND_LABEL[d.kind] || d.kind || '';
    const dateBlock = (d.end_date && d.end_date !== d.date)
      ? `<div class="cal-pop-row"><span class="lbl">Periodo</span><span><b>${_esc(fmtDate(d.date))}</b> → <b style="color:${color}">${_esc(fmtDate(d.end_date))}</b></span></div>`
      : `<div class="cal-pop-row"><span class="lbl">Fecha</span><b>${_esc(fmtDate(d.date))}</b></div>`;

    const statusRow = d.status
      ? `<div class="cal-pop-row"><span class="lbl">Estado</span><span class="cal-pop-status">${_esc(STATUS_LABEL[d.status] || d.status)}</span></div>`
      : '';
    const stationRow = d.station_name
      ? `<div class="cal-pop-row"><span class="lbl">Alcance</span>${_esc(d.station_name)}</div>` : '';
    const moduleRow = d.module
      ? `<div class="cal-pop-row"><span class="lbl">Módulo</span><span class="cal-pop-mod">${_esc(d.module)}</span></div>` : '';
    const fileRow = d.file_type
      ? `<div class="cal-pop-row"><span class="lbl">Formato</span>${_esc(d.file_type)}</div>` : '';
    const descRow = d.description
      ? `<div class="cal-pop-desc">${_esc(d.description)}</div>` : '';

    const overdueBadge = d.overdue
      ? `<span class="cal-pop-overdue">⚠ Vencido</span>` : '';

    popoverEl.innerHTML = `
      <button type="button" class="cal-pop-close" aria-label="Cerrar">×</button>
      <div class="cal-pop-kinds">
        <span class="cal-pop-kind" style="color:${color};background:${color}1a;">
          <span class="cal-pop-dot" style="background:${color}"></span>
          ${_esc(kindLabel)}
        </span>
        ${overdueBadge}
      </div>
      <div class="cal-pop-title">${_esc(d.title || '')}</div>
      ${descRow}
      <div class="cal-pop-grid">
        ${dateBlock}
        ${moduleRow}
        ${stationRow}
        ${fileRow}
        ${statusRow}
      </div>
      <div class="cal-pop-hint">Vista informativa — sin acciones disponibles.</div>
    `;
    popoverEl.classList.add('open');
    popoverBackdropEl.classList.add('open');
  }

  function closePopover() {
    popoverEl.classList.remove('open');
    popoverBackdropEl.classList.remove('open');
  }

  popoverEl.addEventListener('click', (e) => {
    if (e.target.closest('.cal-pop-close')) closePopover();
  });
  popoverBackdropEl.addEventListener('click', closePopover);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && popoverEl.classList.contains('open')) closePopover();
  });

  async function load() {
    const data = await api(`/api/operational-calendar?from=${encodeURIComponent(fromEl.value)}&to=${encodeURIComponent(toEl.value)}`);
    lastItems = data.items || [];
    lastTemplates = data.templates_month || [];
    updateChipCounts(lastItems);
    renderTemplates(lastTemplates);
    renderEvents();
  }

  qs('#btnReload').addEventListener('click', load);
  await load();
})();
