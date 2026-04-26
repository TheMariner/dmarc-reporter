const payload = JSON.parse(document.getElementById("report-data").textContent);
const summaryGrid = document.getElementById("summary-grid");
const chartGrid = document.getElementById("chart-grid");
const insightGrid = document.getElementById("insight-grid");
const insightHero = document.getElementById("insight-hero");
const sidebarControls = document.getElementById("sidebar-controls");
const viewNav = document.getElementById("view-nav");
const tableRoot = document.getElementById("record-table");
const partialDataBanner = document.getElementById("partial-data-banner");
const statusStrip = document.getElementById("status-strip");
const detailShell = document.getElementById("detail-shell");
const detailNote = document.getElementById("detail-note");
const mainPane = document.getElementById("main-pane-scroll");

const experience = payload.report_experience ?? {
  available_views: ["overview"],
  filters: { reporters: [], compliance_categories: [], dispositions: [] },
  top_results_visible_limit: 5,
};
const initialState = experience.initial_state ?? {
  active_view: "overview",
  selected_reporters: [],
  selected_compliance_categories: [],
  selected_dispositions: [],
  detail_expanded: false,
};
const state = {
  activeView: initialState.active_view,
  selectedReporters: new Set(initialState.selected_reporters ?? []),
  selectedComplianceCategories: new Set(initialState.selected_compliance_categories ?? []),
  selectedDispositions: new Set(initialState.selected_dispositions ?? []),
  detailExpanded: Boolean(initialState.detail_expanded),
};

if (payload.summary.partial_data) {
  const reasons = payload.summary.partial_data_reasons ?? [
    "One or more source reports were skipped or failed validation.",
  ];
  partialDataBanner.innerHTML = `
    <div class="alert-card">
      <h2>Partial Data</h2>
      <p>This report was built with skipped or incomplete source data.</p>
      <ul>${reasons.map((reason) => `<li>${reason}</li>`).join("")}</ul>
    </div>
  `;
}

render({ preserveScroll: false });

window.addEventListener("resize", () => {
  renderSidebar();
});

viewNav.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-view]");
  if (!button) {
    return;
  }
  state.activeView = button.dataset.view;
  render({ preserveScroll: true });
});

sidebarControls.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-filter-group]");
  if (!button) {
    return;
  }
  toggleFilter(button.dataset.filterGroup, button.dataset.filterValue);
  state.activeView = "overview";
  render({ preserveScroll: true });
});

detailShell.addEventListener("toggle", () => {
  state.detailExpanded = detailShell.open;
  renderDetailTable(getFilteredRows());
});

function render({ preserveScroll }) {
  const previousScrollTop = preserveScroll ? mainPane.scrollTop : 0;
  renderStatusStrip();
  renderSummaryCards();
  renderViewNav();
  renderSidebar();
  renderInsightHero();
  renderInsights();
  renderCharts();
  renderDetailTable(getFilteredRows());
  if (preserveScroll) {
    requestAnimationFrame(() => {
      mainPane.scrollTop = previousScrollTop;
    });
  }
}

function renderSidebar() {
  const sidebar = experience.sidebar ?? { filter_groups: [] };
  const selectedCount =
    state.selectedReporters.size +
    state.selectedComplianceCategories.size +
    state.selectedDispositions.size;
  const filterPosition = window.matchMedia("(max-width: 960px)").matches ? "top" : "left";
  sidebarControls.innerHTML = `
    <div class="sidebar-card sidebar-instruction-card">
      <p class="sidebar-kicker">How To Use This Report</p>
      <p class="sidebar-copy">Filter this period from the ${filterPosition}.</p>
    </div>
    <div class="section-heading compact">
      <div>
        <p class="section-kicker">Slice This Period</p>
        <h2>${sidebar.title ?? "Interactive Filters"}</h2>
      </div>
    </div>
    <div class="status-pill">${selectedCount} active filters</div>
    <div class="sidebar-filter-stack">
      ${renderInteractiveFilterGroup("reporters", "Reporters", experience.filters.reporters, state.selectedReporters)}
      ${renderInteractiveFilterGroup("compliance", "Compliance", experience.filters.compliance_categories, state.selectedComplianceCategories)}
      ${renderInteractiveFilterGroup("dispositions", "Disposition", experience.filters.dispositions, state.selectedDispositions)}
    </div>
  `;
}

function renderStatusStrip() {
  const statuses = [
    `Completeness: ${payload.period.completeness_status}`,
    `Refresh: ${payload.period.refresh_status ?? "current"}`,
    `Partial Data: ${payload.summary.partial_data ? "yes" : "no"}`,
    `Cadence: ${payload.period.period_type}`,
  ];
  statusStrip.innerHTML = statuses.map((status) => `<span class="status-pill">${status}</span>`).join("");
}

function renderSummaryCards() {
  const rows = getFilteredRows();
  const totalMessages = rows.reduce((sum, row) => sum + Number(row.count || 0), 0);
  const topReporter = rankRows(rows, "reporter")[0]?.label ?? "n/a";
  const nonCompliant = rows
    .filter((row) => row.compliance_category === "non_compliant")
    .reduce((sum, row) => sum + Number(row.count || 0), 0);
  const topSource = rankRows(rows, "source_ip")[0]?.label ?? "n/a";
  const cards = [
    ["Visible Messages", totalMessages],
    ["Visible Records", rows.length],
    ["Top Reporter", topReporter],
    ["Top Source", topSource],
    ["Non-Compliant", nonCompliant],
  ];
  summaryGrid.innerHTML = cards
    .map(
      ([label, value]) => `
        <article class="panel-card summary-card">
          <p class="card-label">${label}</p>
          <div class="summary-value">${value}</div>
        </article>
      `
    )
    .join("");
}

function renderViewNav() {
  viewNav.innerHTML = experience.available_views
    .map((view) => {
      const active = state.activeView === view ? " is-active" : "";
      const label = view === "details" ? "detail" : view.replace("_", " ");
      return `<button type="button" class="view-pill${active}" data-view="${view}">${label}</button>`;
    })
    .join("");
}

function renderInsightHero() {
  const copy = {
    overview: "Top findings first, with suspicious activity surfaced ahead of the long tail.",
    reporters: "Compare reporter volume and reporter-driven non-compliant activity without leaving the artifact.",
    sources: "Inspect sending sources by volume and spoofing risk signal.",
    compliance: "Pivot between compliant and non-compliant traffic while keeping disposition visible as its own lens.",
    details: "The detail table remains available without polluting first load.",
  };
  const heading = {
    overview: "Overview",
    reporters: "Reporter View",
    sources: "Source View",
    compliance: "Compliance View",
    details: "Detail View",
  };
  insightHero.innerHTML = `
    <article class="panel-card hero-card content-section" data-section-id="hero">
      <div class="section-heading compact">
        <div>
          <p class="section-kicker">Interactive Report</p>
          <h2>${heading[state.activeView] ?? "Overview"}</h2>
        </div>
        <p class="section-copy">${copy[state.activeView] ?? copy.overview}</p>
      </div>
    </article>
  `;
}

function renderInteractiveFilterGroup(groupKey, title, values, selectedSet) {
  const options = (values ?? [])
    .map((value) => {
      const active = selectedSet.has(value) ? " is-active" : "";
      return `
        <button
          type="button"
          class="filter-chip${active}"
          data-filter-group="${groupKey}"
          data-filter-value="${value}"
          aria-pressed="${selectedSet.has(value)}"
        >
          ${value}
        </button>
      `;
    })
    .join("");
  return `
    <section class="sidebar-filter-group">
      <div class="section-heading compact">
        <div>
          <p class="section-kicker">${title}</p>
          <h3>${title}</h3>
        </div>
      </div>
      <div class="filter-chip-row">${options || '<span class="filter-chip is-empty">No values</span>'}</div>
    </section>
  `;
}

function renderInsights() {
  const rows = getFilteredRows();
  const cards = getInsightCards(rows, state.activeView);
  insightGrid.innerHTML = cards
    .map(
      (card) => `
        <article class="panel-card insight-card content-section" data-section-id="${card.sectionId}">
          <div class="section-heading compact">
            <div>
              <p class="section-kicker">Top Results</p>
              <h2>${card.title}</h2>
            </div>
            <p class="section-copy">${card.copy}</p>
          </div>
          <ul class="top-results-list">${renderTopResultsList(card.items)}</ul>
        </article>
      `
    )
    .join("");
}

function getInsightCards(rows, activeView) {
  if (activeView === "reporters") {
    return [makeInsightCard("reporters", "Top Reporters", "Prioritized by suspicious non-compliant activity first.", rankRows(rows, "reporter"))];
  }
  if (activeView === "sources") {
    return [makeInsightCard("sources", "Top Sources", "Source IPs ordered by non-compliant weight, then overall volume.", rankRows(rows, "source_ip"))];
  }
  if (activeView === "compliance") {
    return [
      makeInsightCard("compliance", "Compliance Categories", "DMARC pass and alignment are treated as compliant. Everything else is non-compliant.", rankRows(rows, "compliance_category")),
      makeInsightCard("disposition", "Disposition Outcomes", "Disposition stays separate so you can see how receivers handled the traffic.", rankRows(rows, "disposition")),
    ];
  }
  if (activeView === "details") {
    return [makeInsightCard("details", "Visible Detail Summary", "The deeper table stays in the report, but it stays collapsed by default.", rankRows(rows, "reporter"))];
  }
  return [
    makeInsightCard("reporters", "Top Reporters", "Reporter volume is mixed with non-compliant risk to surface the most actionable organizations first.", rankRows(rows, "reporter")),
    makeInsightCard("sources", "Top Sources", "Source IPs highlight where compliant and non-compliant activity is concentrated.", rankRows(rows, "source_ip")),
    makeInsightCard("compliance", "Compliance Categories", "Non-compliant traffic is shown separately from compliant traffic for spoofing analysis.", rankRows(rows, "compliance_category")),
  ];
}

function makeInsightCard(sectionId, title, copy, items) {
  return { sectionId, title, copy, items: items.slice(0, experience.top_results_visible_limit ?? 5) };
}

function renderTopResultsList(items) {
  if (!items.length) {
    return "<li><span>No data</span><strong>0</strong></li>";
  }
  return items
    .map(
      (item) => `
        <li>
          <span>${item.label}</span>
          <strong>${item.messageCount}</strong>
        </li>
      `
    )
    .join("");
}

function renderCharts() {
  const rows = getFilteredRows();
  const counters = [
    ["Disposition Outcomes", countBy(rows, "disposition")],
    ["Compliance Categories", countBy(rows, "compliance_category")],
    ["DKIM Results", countBy(rows, "dkim_result")],
    ["SPF Results", countBy(rows, "spf_result")],
  ];
  chartGrid.innerHTML = counters
    .map(([title, values]) => renderMetricCard(title, values))
    .join("");
}

function renderMetricCard(title, counters) {
  const entries = Object.entries(counters);
  const maxValue = Math.max(...entries.map((entry) => entry[1]), 1);
  const rows = entries
    .map(([label, value]) => {
      const percent = Math.round((value / maxValue) * 100);
      return `
        <li class="metric-row">
          <span>${label}</span>
          <div class="metric-bar"><div class="metric-fill" style="width:${percent}%"></div></div>
          <strong>${value}</strong>
        </li>
      `;
    })
    .join("");
  return `<article class="panel-card chart-card"><h2>${title}</h2><ul class="metric-list">${rows}</ul></article>`;
}

function renderDetailTable(rows) {
  const limit = experience.detail_visibility?.initial_row_limit ?? 10;
  const visibleRows = state.detailExpanded ? rows : rows.slice(0, limit);
  const rowMarkup = visibleRows
    .map(
      (record) => `
        <tr>
          <td>${record.reporter}</td>
          <td>${record.source_ip}</td>
          <td>${record.header_from}</td>
          <td>${record.count}</td>
          <td>${record.compliance_category}</td>
          <td>${record.disposition}</td>
          <td>${record.dkim_result}</td>
          <td>${record.spf_result}</td>
        </tr>
      `
    )
    .join("");
  detailShell.open = state.detailExpanded;
  detailShell.querySelector("summary").textContent = state.detailExpanded
    ? experience.detail_visibility?.collapse_label ?? "Show fewer detail rows"
    : experience.detail_visibility?.expand_label ?? "Show full detail table";
  detailNote.textContent = state.detailExpanded
    ? `Showing all ${rows.length} rows in the selected slice.`
    : `Showing ${visibleRows.length} of ${rows.length} rows for the current slice.`;
  tableRoot.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Reporter</th>
          <th>Source IP</th>
          <th>Header From</th>
          <th>Count</th>
          <th>Compliance</th>
          <th>Disposition</th>
          <th>DKIM</th>
          <th>SPF</th>
        </tr>
      </thead>
      <tbody>${rowMarkup}</tbody>
    </table>
  `;
}

function getFilteredRows() {
  return (payload.summary.records ?? []).filter((row) => {
    if (state.selectedReporters.size && !state.selectedReporters.has(row.reporter)) {
      return false;
    }
    if (state.selectedComplianceCategories.size && !state.selectedComplianceCategories.has(row.compliance_category)) {
      return false;
    }
    if (state.selectedDispositions.size && !state.selectedDispositions.has(row.disposition)) {
      return false;
    }
    return true;
  });
}

function toggleFilter(group, value) {
  const target = group === "reporters"
    ? state.selectedReporters
    : group === "compliance"
      ? state.selectedComplianceCategories
      : state.selectedDispositions;
  if (target.has(value)) {
    target.delete(value);
  } else {
    target.add(value);
  }
}

function rankRows(rows, key) {
  const buckets = new Map();
  rows.forEach((row) => {
    const bucketKey = row[key] ?? "unknown";
    if (!buckets.has(bucketKey)) {
      buckets.set(bucketKey, { label: bucketKey, messageCount: 0, riskWeight: 0 });
    }
    const bucket = buckets.get(bucketKey);
    bucket.messageCount += Number(row.count || 0);
    bucket.riskWeight += row.compliance_category === "non_compliant" ? Number(row.count || 0) : 0;
  });
  return Array.from(buckets.values()).sort((left, right) => {
    if (right.riskWeight !== left.riskWeight) {
      return right.riskWeight - left.riskWeight;
    }
    if (right.messageCount !== left.messageCount) {
      return right.messageCount - left.messageCount;
    }
    return String(left.label).localeCompare(String(right.label));
  });
}

function countBy(rows, key) {
  return rows.reduce((accumulator, row) => {
    const label = row[key] ?? "unknown";
    accumulator[label] = (accumulator[label] ?? 0) + Number(row.count || 0);
    return accumulator;
  }, {});
}
