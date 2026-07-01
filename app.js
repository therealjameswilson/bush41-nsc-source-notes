const DATA_URL = "data/entries.min.json";
const INITIAL_RESULTS = 1000;
const RESULTS_BATCH = 1000;
const SCROLL_LOAD_MARGIN = 1800;

const state = {
  entries: [],
  matches: [],
  query: "",
  queryTerms: [],
  series: "all",
  rowFilter: "all",
  renderedCount: 0,
  renderQueued: false,
};

const els = {
  entryCount: document.querySelector("#entryCount"),
  folderCount: document.querySelector("#folderCount"),
  seriesCount: document.querySelector("#seriesCount"),
  onlineCount: document.querySelector("#onlineCount"),
  search: document.querySelector("#searchInput"),
  series: document.querySelector("#seriesFilter"),
  rowFilter: document.querySelector("#rowFilter"),
  reset: document.querySelector("#resetFilters"),
  copyFiltered: document.querySelector("#copyFiltered"),
  copyStatus: document.querySelector("#copyStatus"),
  resultCount: document.querySelector("#resultCount"),
  body: document.querySelector("#resultsBody"),
  rowTemplate: document.querySelector("#rowTemplate"),
};

function formatNumber(value) {
  return Number(value || 0).toLocaleString("en-US");
}

function normalizeEntry(entry) {
  const normalized = {
    sourceNote: entry.n,
    entryType: entry.t,
    sourceSeries: entry.ss,
    seriesTitle: entry.st,
    seriesLocalId: entry.sl,
    seriesNaid: entry.sn,
    folderTitle: entry.f,
    localId: entry.oa,
    fileUnitNaid: entry.na,
    availability: entry.a,
    recordTypes: entry.rt,
    catalogUrl: entry.c,
    onlineUrl: entry.o,
  };
  normalized.haystack = [
    normalized.sourceNote,
    normalized.sourceSeries,
    normalized.seriesTitle,
    normalized.seriesLocalId,
    normalized.seriesNaid,
    normalized.folderTitle,
    normalized.localId,
    normalized.fileUnitNaid,
    normalized.availability,
    normalized.recordTypes,
  ]
    .join(" ")
    .toLowerCase();
  return normalized;
}

function populateSeries(seriesRows) {
  const options = [...seriesRows]
    .filter((row) => row.s)
    .sort((a, b) => String(a.s).localeCompare(String(b.s)))
    .map((row) => ({ value: row.s, label: row.s }));
  const seen = new Set();
  options.forEach((option) => {
    if (seen.has(option.value)) return;
    seen.add(option.value);
    const node = document.createElement("option");
    node.value = option.value;
    node.textContent = option.label;
    els.series.appendChild(node);
  });
}

function matchesQuery(entry) {
  return !state.queryTerms.length || state.queryTerms.every((term) => entry.haystack.includes(term));
}

function matchesSeries(entry) {
  return state.series === "all" || entry.sourceSeries === state.series;
}

function matchesRowFilter(entry) {
  if (state.rowFilter === "all") return true;
  if (state.rowFilter === "folder") return entry.entryType === "folder";
  if (state.rowFilter === "series_stem") return entry.entryType === "series_stem";
  if (state.rowFilter === "online") return entry.availability === "Online";
  if (state.rowFilter === "onsite") return entry.availability === "On Site";
  if (state.rowFilter === "naid") return entry.entryType === "folder" && !entry.localId && entry.fileUnitNaid;
  return true;
}

function applyFilters() {
  state.matches = state.entries.filter((entry) => matchesQuery(entry) && matchesSeries(entry) && matchesRowFilter(entry));
  state.renderedCount = 0;
  els.body.replaceChildren();
  appendResults(INITIAL_RESULTS);
}

function updateResultCount() {
  const totalMatches = state.matches.length;
  const shown = state.renderedCount;
  const showingText = shown === totalMatches ? `showing all ${formatNumber(shown)}` : `showing ${formatNumber(shown)}`;
  els.resultCount.textContent = `${formatNumber(totalMatches)} matches; ${showingText}`;
}

function addMetaLink(parts, url, label) {
  if (!url) return;
  parts.push(`<a href="${url}" target="_blank" rel="noreferrer">${label}</a>`);
}

function locatorText(entry) {
  if (entry.localId) return `OA/ID ${entry.localId}`;
  if (entry.fileUnitNaid) return `NAID ${entry.fileUnitNaid}`;
  if (entry.seriesLocalId) return entry.seriesLocalId;
  return "";
}

function appendResults(count) {
  const totalMatches = state.matches.length;

  if (!totalMatches) {
    updateResultCount();
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.className = "empty";
    cell.textContent = "No matching entries.";
    row.appendChild(cell);
    els.body.appendChild(row);
    return;
  }

  const nextEntries = state.matches.slice(state.renderedCount, state.renderedCount + count);
  state.renderedCount += nextEntries.length;

  const fragment = document.createDocumentFragment();
  nextEntries.forEach((entry) => {
    const row = els.rowTemplate.content.firstElementChild.cloneNode(true);
    row.querySelector(".source-note").textContent = entry.sourceNote;
    row.querySelector(".locator-cell").textContent = locatorText(entry);
    row.querySelector(".series-cell").textContent = entry.sourceSeries;
    row.querySelector(".access-cell").textContent = entry.availability || "Series stem";

    const metaParts = [];
    if (entry.seriesTitle && entry.seriesTitle !== entry.sourceSeries) metaParts.push(`Finding-aid heading: ${entry.seriesTitle}`);
    if (entry.fileUnitNaid) metaParts.push(`NAID ${entry.fileUnitNaid}`);
    if (entry.recordTypes) metaParts.push(entry.recordTypes);
    addMetaLink(metaParts, entry.catalogUrl, "Catalog");
    addMetaLink(metaParts, entry.onlineUrl, "Online object");
    row.querySelector(".row-meta").innerHTML = metaParts.join(" | ");

    row.querySelector(".copy-row").addEventListener("click", () => {
      copyText(entry.sourceNote, "Copied one source note.");
    });
    fragment.appendChild(row);
  });
  els.body.appendChild(fragment);
  updateResultCount();
  queueScrollCheck();
}

function hasMoreResults() {
  return state.renderedCount < state.matches.length;
}

function nearPageBottom() {
  const scrollBottom = window.scrollY + window.innerHeight;
  return document.documentElement.scrollHeight - scrollBottom < SCROLL_LOAD_MARGIN;
}

function queueScrollCheck() {
  if (state.renderQueued) return;
  state.renderQueued = true;
  requestAnimationFrame(() => {
    state.renderQueued = false;
    if (hasMoreResults() && nearPageBottom()) appendResults(RESULTS_BATCH);
  });
}

async function copyText(text, successMessage) {
  try {
    await navigator.clipboard.writeText(text);
    els.copyStatus.textContent = successMessage;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    els.copyStatus.textContent = successMessage;
  }
}

function debounce(fn, delay = 140) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

async function loadData() {
  const response = await fetch(DATA_URL);
  if (!response.ok) throw new Error(`Could not load ${DATA_URL}`);
  const payload = await response.json();
  const summary = payload.summary || {};

  state.entries = (payload.entries || []).map(normalizeEntry);
  populateSeries(payload.series || []);

  els.entryCount.textContent = formatNumber(summary.entry_count || state.entries.length);
  els.folderCount.textContent = formatNumber(summary.folder_entry_count || 0);
  els.seriesCount.textContent = formatNumber(summary.series_count || 0);
  els.onlineCount.textContent = formatNumber(summary.online_folder_entry_count || 0);
  applyFilters();
}

els.search.addEventListener(
  "input",
  debounce((event) => {
    state.query = event.target.value.trim().toLowerCase();
    state.queryTerms = state.query.split(/\s+/).filter(Boolean);
    applyFilters();
  }),
);

els.series.addEventListener("change", (event) => {
  state.series = event.target.value;
  applyFilters();
});

els.rowFilter.addEventListener("change", (event) => {
  state.rowFilter = event.target.value;
  applyFilters();
});

els.reset.addEventListener("click", () => {
  state.query = "";
  state.queryTerms = [];
  state.series = "all";
  state.rowFilter = "all";
  els.search.value = "";
  els.series.value = "all";
  els.rowFilter.value = "all";
  els.copyStatus.textContent = "";
  applyFilters();
});

els.copyFiltered.addEventListener("click", () => {
  const notes = state.matches.map((entry) => entry.sourceNote).join("\n");
  copyText(notes, `Copied ${formatNumber(state.matches.length)} source notes.`);
});

window.addEventListener("scroll", queueScrollCheck, { passive: true });
window.addEventListener("resize", queueScrollCheck);

loadData().catch((error) => {
  els.resultCount.textContent = error.message;
});
