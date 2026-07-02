const DATA_URL = "data/entries.min.json";
const PAGE_SIZE = 1000;

const state = {
  entries: [],
  matches: [],
  query: "",
  queryTerms: [],
  sourceGroup: "all",
  series: "all",
  rowFilter: "all",
  pageIndex: 0,
};

const els = {
  entryCount: document.querySelector("#entryCount"),
  folderCount: document.querySelector("#folderCount"),
  seriesCount: document.querySelector("#seriesCount"),
  onlineCount: document.querySelector("#onlineCount"),
  search: document.querySelector("#searchInput"),
  sourceGroup: document.querySelector("#sourceGroupFilter"),
  series: document.querySelector("#seriesFilter"),
  rowFilter: document.querySelector("#rowFilter"),
  reset: document.querySelector("#resetFilters"),
  copyFiltered: document.querySelector("#copyFiltered"),
  copyStatus: document.querySelector("#copyStatus"),
  resultCount: document.querySelector("#resultCount"),
  pageStatus: document.querySelector("#pageStatus"),
  pageSelect: document.querySelector("#pageSelect"),
  previousPage: document.querySelector("#previousPage"),
  nextPage: document.querySelector("#nextPage"),
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
    sourceGroup: entry.g,
    sourcePrefix: entry.p,
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
    normalized.sourceGroup,
    normalized.sourcePrefix,
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

function populateSourceGroups(entries) {
  const groups = [...new Set(entries.map((entry) => entry.sourceGroup).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b),
  );
  groups.forEach((group) => {
    const node = document.createElement("option");
    node.value = group;
    node.textContent = group;
    els.sourceGroup.appendChild(node);
  });
}

function matchesQuery(entry) {
  return !state.queryTerms.length || state.queryTerms.every((term) => entry.haystack.includes(term));
}

function matchesSourceGroup(entry) {
  return state.sourceGroup === "all" || entry.sourceGroup === state.sourceGroup;
}

function matchesSeries(entry) {
  return state.series === "all" || entry.sourceSeries === state.series;
}

function matchesRowFilter(entry) {
  if (state.rowFilter === "all") return true;
  if (state.rowFilter === "folder") return entry.entryType === "folder";
  if (state.rowFilter === "series_stem") return entry.entryType === "series_stem";
  if (state.rowFilter === "item") return entry.entryType === "item";
  if (state.rowFilter === "online") return entry.availability === "Online";
  if (state.rowFilter === "onsite") return entry.availability === "On Site";
  if (state.rowFilter === "naid") return entry.entryType === "folder" && !entry.localId && entry.fileUnitNaid;
  return true;
}

function applyFilters() {
  state.matches = state.entries.filter(
    (entry) => matchesQuery(entry) && matchesSourceGroup(entry) && matchesSeries(entry) && matchesRowFilter(entry),
  );
  state.pageIndex = 0;
  renderPage();
}

function totalPages() {
  return Math.max(1, Math.ceil(state.matches.length / PAGE_SIZE));
}

function currentPageEntries() {
  const start = state.pageIndex * PAGE_SIZE;
  return state.matches.slice(start, start + PAGE_SIZE);
}

function updateResultCount(pageEntries) {
  const totalMatches = state.matches.length;
  if (!totalMatches) {
    els.resultCount.textContent = "0 matches";
    return;
  }
  const start = state.pageIndex * PAGE_SIZE + 1;
  const end = start + pageEntries.length - 1;
  els.resultCount.textContent = `${formatNumber(totalMatches)} matches; showing ${formatNumber(start)}-${formatNumber(end)}`;
}

function updatePagerControls() {
  const totalMatches = state.matches.length;
  const pages = totalPages();
  els.pageSelect.replaceChildren();

  if (!totalMatches) {
    const option = document.createElement("option");
    option.value = "0";
    option.textContent = "No pages";
    els.pageSelect.appendChild(option);
    els.pageSelect.disabled = true;
    els.previousPage.disabled = true;
    els.nextPage.disabled = true;
    els.pageStatus.textContent = "Page 0 of 0";
    return;
  }

  for (let index = 0; index < pages; index += 1) {
    const start = index * PAGE_SIZE + 1;
    const end = Math.min((index + 1) * PAGE_SIZE, totalMatches);
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = `Page ${formatNumber(index + 1)} (${formatNumber(start)}-${formatNumber(end)})`;
    els.pageSelect.appendChild(option);
  }

  els.pageSelect.value = String(state.pageIndex);
  els.pageSelect.disabled = pages <= 1;
  els.previousPage.disabled = state.pageIndex === 0;
  els.nextPage.disabled = state.pageIndex >= pages - 1;
  els.pageStatus.textContent = `Page ${formatNumber(state.pageIndex + 1)} of ${formatNumber(pages)}`;
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

function renderPage() {
  const totalMatches = state.matches.length;
  const pageEntries = currentPageEntries();
  els.body.replaceChildren();

  if (!totalMatches) {
    updateResultCount(pageEntries);
    updatePagerControls();
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.className = "empty";
    cell.textContent = "No matching entries.";
    row.appendChild(cell);
    els.body.appendChild(row);
    return;
  }

  const fragment = document.createDocumentFragment();
  pageEntries.forEach((entry) => {
    const row = els.rowTemplate.content.firstElementChild.cloneNode(true);
    row.querySelector(".source-note").textContent = entry.sourceNote;
    row.querySelector(".locator-cell").textContent = locatorText(entry);
    row.querySelector(".series-cell").textContent = entry.sourceSeries;
    row.querySelector(".access-cell").textContent = entry.availability || "Series stem";

    const metaParts = [];
    if (entry.sourceGroup) metaParts.push(entry.sourceGroup);
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
  updateResultCount(pageEntries);
  updatePagerControls();
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
  populateSourceGroups(state.entries);
  populateSeries(payload.series || []);

  els.entryCount.textContent = formatNumber(summary.entry_count || state.entries.length);
  els.folderCount.textContent = formatNumber(summary.folder_entry_count || 0);
  els.seriesCount.textContent = formatNumber(summary.series_count || 0);
  els.onlineCount.textContent = formatNumber(summary.online_entry_count || summary.online_folder_entry_count || 0);
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

els.sourceGroup.addEventListener("change", (event) => {
  state.sourceGroup = event.target.value;
  applyFilters();
});

els.rowFilter.addEventListener("change", (event) => {
  state.rowFilter = event.target.value;
  applyFilters();
});

els.previousPage.addEventListener("click", () => {
  if (state.pageIndex <= 0) return;
  state.pageIndex -= 1;
  renderPage();
  document.querySelector("#results-heading").scrollIntoView({ block: "start" });
});

els.nextPage.addEventListener("click", () => {
  if (state.pageIndex >= totalPages() - 1) return;
  state.pageIndex += 1;
  renderPage();
  document.querySelector("#results-heading").scrollIntoView({ block: "start" });
});

els.pageSelect.addEventListener("change", (event) => {
  state.pageIndex = Number(event.target.value || 0);
  renderPage();
  document.querySelector("#results-heading").scrollIntoView({ block: "start" });
});

els.reset.addEventListener("click", () => {
  state.query = "";
  state.queryTerms = [];
  state.sourceGroup = "all";
  state.series = "all";
  state.rowFilter = "all";
  els.search.value = "";
  els.sourceGroup.value = "all";
  els.series.value = "all";
  els.rowFilter.value = "all";
  els.copyStatus.textContent = "";
  applyFilters();
});

els.copyFiltered.addEventListener("click", () => {
  const pageEntries = currentPageEntries();
  const notes = pageEntries.map((entry) => entry.sourceNote).join("\n");
  copyText(notes, `Copied ${formatNumber(pageEntries.length)} source notes from this page.`);
});

loadData().catch((error) => {
  els.resultCount.textContent = error.message;
});
