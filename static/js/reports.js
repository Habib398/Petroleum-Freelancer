(async () => {
  // ---------- Descargas (sección original) ----------
  const rmBtn = qs("#rmBtn");
  const raBtn = qs("#raBtn");
  if (rmBtn) rmBtn.addEventListener("click", () => {
    const y = qs("#rmYear").value;
    const m = qs("#rmMonth").value;
    window.open(`/api/reports/monthly.pdf?year=${encodeURIComponent(y)}&month=${encodeURIComponent(m)}`, "_blank");
  });
  if (raBtn) raBtn.addEventListener("click", () => {
    const y = qs("#raYear").value;
    window.open(`/api/reports/annual.pdf?year=${encodeURIComponent(y)}`, "_blank");
  });

  // ---------- Cumplimiento ----------
  const forbiddenEl = qs("#repForbidden");
  const analyticsEl = qs("#repAnalytics");
  const yearSel = qs("#repYear");
  const stationSel = qs("#repStation");
  const stationGroup = qs("#repStationGroup");
  const todayLabel = qs("#repTodayLabel");
  const monthlySubEl = qs("#repMonthlySub");
  const rankCard = qs("#repRankCard");
  const rankList = qs("#repRankList");

  let me = null;
  try { me = (await api("/api/me")).me; } catch (e) { return; }

  const role = me && me.role;
  if (role !== "admin" && role !== "jefe_estacion") {
    forbiddenEl.hidden = false;
    return;
  }
  analyticsEl.hidden = false;

  // Año actual + 2 atrás
  const now = new Date();
  const curYear = now.getFullYear();
  yearSel.innerHTML = "";
  for (let y = curYear; y >= curYear - 3; y--) {
    yearSel.insertAdjacentHTML("beforeend", `<option value="${y}">${y}</option>`);
  }
  yearSel.value = String(curYear);

  // Chart instances
  let chartMonthly = null;
  let chartWeekly = null;

  function toneFor(pct, total) {
    if (!total) return "tone-zero";
    if (pct < 50) return "tone-red";
    if (pct < 80) return "tone-amber";
    return "tone-green";
  }

  function setKpi(key, data) {
    const card = qs(`.rep-kpi[data-kpi="${key}"]`);
    if (!card) return;
    const done = (data && data.done) || 0;
    const total = (data && data.total) || 0;
    const pct = (data && data.pct) || 0;
    card.classList.remove("tone-red", "tone-amber", "tone-green", "tone-zero");
    card.classList.add(toneFor(pct, total));
    card.querySelector(".pct").textContent = total ? `${pct}%` : "—";
    card.querySelector(".ratio").textContent = `${done} / ${total}`;
    card.querySelector(".bar > span").style.width = `${total ? pct : 0}%`;
  }

  function setStationSelect(stations, selectedId) {
    const opts = [`<option value="all">Todas</option>`];
    stations.forEach(s => {
      const sel = (selectedId && s.id === selectedId) ? " selected" : "";
      opts.push(`<option value="${s.id}"${sel}>${_esc(s.code || "")} • ${_esc(s.name || "")}</option>`);
    });
    stationSel.innerHTML = opts.join("");
    if (selectedId) stationSel.value = String(selectedId);
  }

  function renderMonthlyChart(byMonth) {
    const labels = byMonth.map(m => m.label);
    const data = byMonth.map(m => m.pct);
    const totals = byMonth.map(m => m.total);
    const dones = byMonth.map(m => m.done);

    const colors = data.map((pct, i) => {
      if (!totals[i]) return "rgba(148, 163, 184, .55)";
      if (pct < 50) return "rgba(220, 38, 38, .75)";
      if (pct < 80) return "rgba(245, 158, 11, .80)";
      return "rgba(34, 197, 94, .80)";
    });

    if (chartMonthly) chartMonthly.destroy();
    chartMonthly = new Chart(qs("#repChartMonthly"), {
      type: "bar",
      data: {
        labels,
        datasets: [{
          label: "% cumplido",
          data,
          backgroundColor: colors,
          borderRadius: 6,
          borderSkipped: false,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const i = ctx.dataIndex;
                return `${dones[i]} / ${totals[i]} (${data[i]}%)`;
              },
            },
          },
        },
        scales: {
          y: {
            beginAtZero: true, max: 100,
            ticks: { callback: (v) => v + "%", font: { size: 11 } },
            grid: { color: "rgba(2,6,23,.06)" },
          },
          x: { grid: { display: false }, ticks: { font: { size: 11 } } },
        },
      },
    });
  }

  function renderWeeklyChart(byWeeks) {
    const labels = byWeeks.map(w => w.label);
    const data = byWeeks.map(w => w.pct);
    const totals = byWeeks.map(w => w.total);
    const dones = byWeeks.map(w => w.done);

    if (chartWeekly) chartWeekly.destroy();
    chartWeekly = new Chart(qs("#repChartWeekly"), {
      type: "line",
      data: {
        labels,
        datasets: [{
          label: "% cumplido",
          data,
          borderColor: "rgba(134, 184, 33, .95)",
          backgroundColor: "rgba(134, 184, 33, .15)",
          borderWidth: 2.5,
          pointBackgroundColor: "#86B821",
          pointRadius: 4,
          pointHoverRadius: 6,
          fill: true,
          tension: 0.3,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const i = ctx.dataIndex;
                return `${dones[i]} / ${totals[i]} (${data[i]}%)`;
              },
            },
          },
        },
        scales: {
          y: {
            beginAtZero: true, max: 100,
            ticks: { callback: (v) => v + "%", font: { size: 11 } },
            grid: { color: "rgba(2,6,23,.06)" },
          },
          x: { grid: { display: false }, ticks: { font: { size: 11 } } },
        },
      },
    });
  }

  function renderRanking(byStation) {
    if (!byStation || !byStation.length) {
      rankCard.hidden = true;
      return;
    }
    rankCard.hidden = false;
    rankList.innerHTML = byStation.map(s => {
      const tone = toneFor(s.pct, s.total);
      return `<div class="rep-rank-row ${tone}">
        <div>
          <div class="name">${_esc(s.name || "")}</div>
          <div class="code">${_esc(s.code || "")}</div>
        </div>
        <div class="code">${s.done} / ${s.total}</div>
        <div class="bar"><span style="width:${s.total ? s.pct : 0}%"></span></div>
        <div class="pct">${s.total ? s.pct + "%" : "—"}</div>
      </div>`;
    }).join("");
  }

  async function load() {
    const year = yearSel.value;
    const station = stationSel.value;
    const params = new URLSearchParams({ year });
    if (station && station !== "all") params.set("station_id", station);
    const data = await api(`/api/reports/activity-compliance?${params.toString()}`);

    todayLabel.textContent = `Datos al ${data.today || ""}`;
    monthlySubEl.textContent = `Año ${data.year}`;

    // Si no hay estaciones accesibles, esconder lo demás
    if (!data.stations_accessible || !data.stations_accessible.length) {
      analyticsEl.querySelector(".rep-kpis").style.opacity = ".5";
      stationGroup.hidden = true;
      return;
    }

    // Populate station select solo la primera vez
    if (!stationSel.dataset.populated) {
      setStationSelect(data.stations_accessible, data.selected_station_id);
      stationSel.dataset.populated = "1";
      // Jefe de estación con una sola estación: no necesita selector
      if (role !== "admin" && data.stations_accessible.length <= 1) {
        stationGroup.hidden = true;
      }
    }

    setKpi("daily", data.period.daily);
    setKpi("weekly", data.period.weekly);
    setKpi("monthly", data.period.monthly);
    setKpi("yearly", data.period.yearly);

    renderMonthlyChart(data.by_month || []);
    renderWeeklyChart(data.by_weeks || []);

    if (role === "admin") {
      renderRanking(data.by_station || []);
    } else {
      rankCard.hidden = true;
    }
  }

  yearSel.addEventListener("change", load);
  stationSel.addEventListener("change", load);

  try {
    await load();
  } catch (e) {
    forbiddenEl.hidden = false;
    forbiddenEl.textContent = "No se pudo cargar el cumplimiento: " + ((e && e.message) || "error");
    analyticsEl.hidden = true;
  }
})();
