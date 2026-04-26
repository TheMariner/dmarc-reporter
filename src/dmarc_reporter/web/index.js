const payload = JSON.parse(document.getElementById("index-data").textContent);
const sidebarControls = document.getElementById("index-sidebar-controls");
const summaryGrid = document.getElementById("index-summary-grid");
const reportCardGrid = document.getElementById("report-card-grid");
const mainPane = document.getElementById("index-main-pane");

const state = {
  selectedCadence: new Set(payload.catalog.initial_state?.selected_cadence ?? []),
  selectedYears: new Set(payload.catalog.initial_state?.selected_years ?? []),
  selectedMonths: new Set(payload.catalog.initial_state?.selected_months ?? []),
  selectedWeeks: new Set(payload.catalog.initial_state?.selected_weeks ?? []),
};

render({ preserveScroll: false });

sidebarControls.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-filter-group]");
  if (!button) {
    return;
  }
  toggleFilter(button.dataset.filterGroup, button.dataset.filterValue);
  render({ preserveScroll: true });
});

function render({ preserveScroll }) {
  const previousScrollTop = preserveScroll ? mainPane.scrollTop : 0;
  renderSidebar();
  renderSummary();
  renderCards();
  if (preserveScroll) {
    requestAnimationFrame(() => {
      mainPane.scrollTop = previousScrollTop;
    });
  }
}

function renderSidebar() {
  const filters = payload.catalog.filters ?? {};
  const visibleGroups = getVisibleFilterGroups();
  sidebarControls.innerHTML = `
    <div class="section-heading compact">
      <div>
        <p class="section-kicker">Interactive Filters</p>
        <h2>Find A Report</h2>
      </div>
    </div>
    <div class="sidebar-filter-stack cadence-chips">
      ${renderChipGroup("cadence", "Cadence", filters.cadence ?? [], state.selectedCadence)}
      ${renderChipGroup("years", "Year", filters.years ?? [], state.selectedYears)}
      ${visibleGroups.has("months") ? renderChipGroup("months", "Month", filters.months ?? [], state.selectedMonths, formatMonth) : ""}
      ${visibleGroups.has("weeks") ? renderChipGroup("weeks", "Week", filters.weeks ?? [], state.selectedWeeks, (value) => `W${String(value).padStart(2, "0")}`) : ""}
    </div>
  `;
}

function getVisibleFilterGroups() {
  const cadence = Array.from(state.selectedCadence);
  if (cadence.length === 1) {
    if (cadence[0] === "monthly") {
      return new Set(["months"]);
    }
    if (cadence[0] === "weekly") {
      return new Set(["weeks"]);
    }
    if (cadence[0] === "yearly") {
      return new Set();
    }
  }
  return new Set(["months", "weeks"]);
}

function renderChipGroup(group, title, values, selectedSet, formatter = (value) => value) {
  const orderedValues = orderFilterValues(group, values ?? []);
  const options = orderedValues
    .map((value) => {
      const stringValue = String(value);
      const active = selectedSet.has(stringValue) ? " is-active" : "";
      return `
        <button
          type="button"
          class="filter-chip${active}"
          data-filter-group="${group}"
          data-filter-value="${stringValue}"
          aria-pressed="${selectedSet.has(stringValue)}"
        >
          ${formatter(value)}
        </button>
      `;
    })
    .join("");
  return `
    <section class="sidebar-filter-group">
      <p class="section-kicker">${title}</p>
      <div class="filter-chip-row">${options || '<span class="filter-chip is-empty">Unavailable</span>'}</div>
    </section>
  `;
}

function orderFilterValues(group, values) {
  if (group === "months") {
    return [...values].sort((left, right) => Number(left) - Number(right));
  }
  if (group === "weeks") {
    return [...values].sort((left, right) => Number(left) - Number(right));
  }
  if (group === "years") {
    return [...values].sort((left, right) => Number(right) - Number(left));
  }
  return [...values];
}

function renderSummary() {
  const visibleEntries = getVisibleEntries();
  const cards = [
    ["Visible Reports", visibleEntries.length],
    ["Cadences", payload.catalog.filters?.cadence?.length ?? 0],
    ["Years", payload.catalog.filters?.years?.length ?? 0],
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

function renderCards() {
  const visibleEntries = getVisibleEntries();
  if (!visibleEntries.length) {
    reportCardGrid.innerHTML = `
      <article class="panel-card empty-card">
        <p class="section-kicker">No generated reports match this slice</p>
        <h3>Try clearing one or more filters.</h3>
      </article>
    `;
    return;
  }
  reportCardGrid.innerHTML = visibleEntries
    .map(
      (entry) => `
        <a class="panel-card report-card" href="${entry.relative_path}">
          <div class="report-card__eyebrow">${entry.cadence}</div>
          <h3>${entry.display_title}</h3>
          <p>${entry.period_label}</p>
          <dl class="report-meta">
            <div><dt>Year</dt><dd>${entry.report_year}</dd></div>
            ${entry.report_month ? `<div><dt>Month</dt><dd>${formatMonth(entry.report_month)}</dd></div>` : ""}
            ${entry.report_week ? `<div><dt>Week</dt><dd>W${String(entry.report_week).padStart(2, "0")}</dd></div>` : ""}
          </dl>
        </a>
      `
    )
    .join("");
}

function getVisibleEntries() {
  return (payload.catalog.entries ?? []).filter((entry) => {
    if (state.selectedCadence.size && !state.selectedCadence.has(String(entry.cadence))) {
      return false;
    }
    if (state.selectedYears.size && !state.selectedYears.has(String(entry.report_year))) {
      return false;
    }
    if (state.selectedMonths.size) {
      if (entry.report_month == null || !state.selectedMonths.has(String(entry.report_month))) {
        return false;
      }
    }
    if (state.selectedWeeks.size) {
      if (entry.report_week == null || !state.selectedWeeks.has(String(entry.report_week))) {
        return false;
      }
    }
    return true;
  });
}

function toggleFilter(group, value) {
  const target = group === "cadence"
    ? state.selectedCadence
    : group === "years"
      ? state.selectedYears
      : group === "months"
        ? state.selectedMonths
        : state.selectedWeeks;
  if (target.has(value)) {
    target.delete(value);
  } else {
    target.add(value);
  }
  normalizeDependentFilters(group);
}

function normalizeDependentFilters(group) {
  if (group === "months") {
    state.selectedWeeks.clear();
    return;
  }
  if (group === "weeks") {
    state.selectedMonths.clear();
    return;
  }
  if (group !== "cadence") {
    return;
  }
  const cadence = Array.from(state.selectedCadence);
  if (cadence.length !== 1) {
    return;
  }
  if (cadence[0] === "monthly") {
    state.selectedWeeks.clear();
    return;
  }
  if (cadence[0] === "weekly") {
    state.selectedMonths.clear();
    return;
  }
  if (cadence[0] === "yearly") {
    state.selectedMonths.clear();
    state.selectedWeeks.clear();
  }
}

function formatMonth(value) {
  const month = Number(value);
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(2024, month - 1, 1)));
}
