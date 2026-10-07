const technology = document.body.dataset.technology;
const countryFilter = document.getElementById("country-filter");
const sourceFilter = document.getElementById("source-filter");
const companyFilter = document.getElementById("company-filter");
const seniorityFilter = document.getElementById("seniority-filter");
const sortFilter = document.getElementById("sort-filter");
const searchFilter = document.getElementById("search-filter");
const list = document.getElementById("job-list");
const status = document.getElementById("catalog-status");
const loadMore = document.getElementById("load-more");
const filtersModal = document.getElementById("catalog-filters-modal");
const introModal = document.getElementById("catalog-intro-modal");
const pageSize = 50;
let offset = 0;
let total = 0;
let jobs = [];
let searchTimer;

const filterIds = {
  skill: "skill-filter",
  role_family: "role-filter",
  contract_type: "contract-filter",
  working_language: "language-filter",
  company_type: "company-type-filter",
  industry: "industry-filter",
  currency: "currency-filter",
  salary_min: "salary-filter",
  salary_period: "salary-period-filter",
};

const params = new URLSearchParams(location.search);
countryFilter.value = params.get("country") === "BG" ? "BG" : "PL";
const savedTheme = localStorage.getItem("jobagent-theme");
if (savedTheme) document.documentElement.setAttribute("data-theme", savedTheme);

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>'"]/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function safeUrl(value) {
  try {
    const url = new URL(value, location.origin);
    return ["http:", "https:"].includes(url.protocol) ? escapeHtml(url.href) : "#";
  } catch { return "#"; }
}

function formatDate(value) {
  if (!value) return "Date unavailable";
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short" }).format(new Date(value));
}

function facts(job) {
  return job.structured_data && typeof job.structured_data === "object" ? job.structured_data : {};
}

function workLabel() {
  return countryFilter.value === "PL" ? "Poland" : "Bulgaria";
}

function titleCase(value) {
  return String(value || "").replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

function tag(label, kind = "", filter = "q") {
  return `<button type="button" class="b ${kind}" data-filter="${escapeHtml(filter)}" data-value="${escapeHtml(label)}">${escapeHtml(label)}</button>`;
}

function formatCompensation(data) {
  const band = (data.compensation_bands || []).find(item => item.compensation_type === "base") || (data.compensation_bands || [])[0];
  const minimum = band?.amount_min ?? data.salary_min;
  const maximum = band?.amount_max ?? data.salary_max;
  if (minimum == null && maximum == null) return "";
  const range = minimum != null && maximum != null ? `${Number(minimum).toLocaleString()}–${Number(maximum).toLocaleString()}` : `${Number(minimum ?? maximum).toLocaleString()}`;
  const currency = band?.currency || data.salary_currency || "";
  const period = band?.period || data.salary_period || "";
  return `${range} ${currency}${period ? ` / ${period.replace("ly", "")}` : ""}`.trim();
}

function fact(label, value) {
  return value ? `<span><strong>${escapeHtml(label)}</strong>${escapeHtml(value)}</span>` : "";
}

function renderJob(job) {
  const data = facts(job);
  const skills = data.skills || [];
  const stack = [...new Set([
    ...skills.filter(item => item.importance !== "incidental").map(item => item.canonical_name || item.original_name),
    ...(data.stack || []), ...(job.technologies || []),
  ].filter(Boolean))].slice(0, 10);
  const seniority = data.seniority && data.seniority !== "unknown" ? data.seniority : data.seniority_min;
  const badges = [
    tag("Remote", "key"),
    seniority ? tag(titleCase(seniority), "", "seniority") : "",
    data.company_type && data.company_type !== "unknown" ? tag(titleCase(data.company_type), "", "company_type") : "",
    data.product_vs_outsourcing && data.product_vs_outsourcing !== "unknown" ? tag(titleCase(data.product_vs_outsourcing)) : "",
    ...stack.map(item => tag(item, "stack", "skill")),
  ].filter(Boolean).join("");
  const sources = (job.sources || []).map(item => `<button type="button" class="src-badge" data-filter="source" data-value="${escapeHtml(item)}">${escapeHtml(item)}</button>`).join("");
  const eligibilityTitle = job.eligibility_confidence === "high"
    ? "Explicit location eligibility found in source data or the job description."
    : "Eligibility is based on the remote region stated in the posting.";
  const evidence = job.eligibility_evidence ? `<div class="catalog-evidence">Eligibility evidence: ${escapeHtml(job.eligibility_evidence)}</div>` : "";
  const compensation = formatCompensation(data);
  const engagement = [...new Set([...(job.engagement_modes || []), ...(data.contract_types || [])].filter(value => value !== "unknown"))].map(titleCase).join(", ");
  const languages = (data.languages || []).map(item => `${titleCase(item.language)}${item.level ? ` ${item.level}` : ""}`).join(", ") || titleCase(data.working_language === "unknown" ? "" : data.working_language);
  const companyProfile = [data.industry, data.company_stage, data.team_size ? `${data.team_size} team` : ""].filter(Boolean).join(" · ");
  const schedule = [data.timezone_requirement, data.core_hours].filter(Boolean).join(" · ");
  const factsHtml = [
    fact("Compensation", compensation), fact("Engagement", engagement), fact("Role", titleCase(data.role_family)),
    fact("Language", languages), fact("Schedule", schedule), fact("Company", companyProfile),
    data.on_call != null ? fact("On-call", data.on_call ? "Yes" : "No") : "",
    fact("Travel", data.travel_requirement), fact("Office visits", data.office_visit_requirement),
    data.eor_available != null ? fact("EOR available", data.eor_available ? "Yes" : "No") : "",
    data.visa_sponsorship != null ? fact("Visa sponsorship", data.visa_sponsorship ? "Yes" : "No") : "",
    fact("Work authorization", data.work_authorization_requirement),
  ].filter(Boolean).join("");
  const description = job.description
    ? `<button type="button" class="disc-toggle" data-description="${escapeHtml(job.id)}">Description <span aria-hidden="true">⌄</span></button><div class="desc-body" id="desc-${escapeHtml(job.id)}">${escapeHtml(job.description)}</div>`
    : "";

  return `<article class="job" id="card-${escapeHtml(job.id)}"><div class="stripe"></div><div class="job-body">
    <div class="job-top"><div class="job-head"><a class="job-title" href="${safeUrl(job.url)}" target="_blank" rel="noopener nofollow">${escapeHtml(job.title)}</a>
      <div class="job-meta"><button type="button" class="co" data-filter="company" data-value="${escapeHtml(job.company || "")}">${escapeHtml(job.company || "Employer unavailable")}</button><span class="loc">⌖ ${escapeHtml(job.location || "Remote")}</span>${sources}</div>
    </div><span class="eligibility" title="${escapeHtml(eligibilityTitle)}">Eligible from ${workLabel()}</span></div>
    <div class="badges">${badges}</div>
    ${(data.summary || job.excerpt) ? `<p class="verdict">${escapeHtml(data.summary || job.excerpt)}${!data.summary && job.excerpt?.length >= 320 ? "…" : ""}</p>` : ""}
    ${factsHtml ? `<div class="catalog-facts">${factsHtml}</div>` : ""}${evidence}
    ${description ? `<div class="disclosures">${description}</div>` : ""}
    <div class="job-foot"><span class="status-tag new">New</span><span class="job-date">${formatDate(job.posted_at || job.created_at)}</span><a class="view-job" href="${safeUrl(job.url)}" target="_blank" rel="noopener nofollow">View original ↗</a></div>
  </div></article>`;
}

function queryParameters() {
  const query = new URLSearchParams({ technology, country: countryFilter.value, limit: pageSize, offset, sort: sortFilter.value });
  if (searchFilter.value.trim()) query.set("q", searchFilter.value.trim());
  if (sourceFilter.value) query.set("source", sourceFilter.value);
  if (companyFilter.value) query.set("company", companyFilter.value);
  if (seniorityFilter.value) query.set("seniority", seniorityFilter.value);
  Object.entries(filterIds).forEach(([parameter, id]) => {
    const value = document.getElementById(id).value.trim();
    if (value) query.set(parameter, value);
  });
  return query;
}

function activeMoreFilterCount() {
  return Object.values(filterIds).filter(id => document.getElementById(id).value.trim()).length;
}

function renderActiveFilters() {
  const filters = [];
  if (sourceFilter.value) filters.push(["source-filter", `Source: ${sourceFilter.value}`]);
  if (companyFilter.value) filters.push(["company-filter", `Employer: ${companyFilter.value}`]);
  if (seniorityFilter.value) filters.push(["seniority-filter", `Seniority: ${titleCase(seniorityFilter.value)}`]);
  Object.entries(filterIds).forEach(([parameter, id]) => {
    const element = document.getElementById(id);
    if (!element.value.trim()) return;
    const label = element.options ? element.options[element.selectedIndex]?.text : element.value;
    filters.push([id, `${titleCase(parameter)}: ${label}`]);
  });
  const bar = document.getElementById("catalog-filter-bar");
  bar.classList.toggle("on", filters.length > 0);
  document.getElementById("catalog-filter-chips").innerHTML = filters
    .map(([id, label]) => `<span class="fchip">${escapeHtml(label)}<button type="button" data-clear-filter="${escapeHtml(id)}" title="Remove">×</button></span>`)
    .join("");
}

function render() {
  list.innerHTML = jobs.map(renderJob).join("");
  const shown = Math.min(jobs.length, total);
  status.textContent = total ? `Showing ${shown} of ${total} jobs` : "No current jobs match these filters.";
  loadMore.hidden = shown >= total;
  document.getElementById("filter-count").textContent = activeMoreFilterCount() || "";
  renderActiveFilters();
}

function setOptions(element, values, emptyLabel) {
  const selected = element.value;
  element.innerHTML = `<option value="">${escapeHtml(emptyLabel)}</option>` + values.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
  if (values.includes(selected)) element.value = selected;
}

async function loadFilterOptions() {
  const response = await fetch(`/api/public/jobs/filter-options?technology=${encodeURIComponent(technology)}&country=${countryFilter.value}`);
  if (!response.ok) return;
  const options = await response.json();
  setOptions(sourceFilter, options.sources || [], "All sources");
  setOptions(companyFilter, options.companies || [], "All employers");
  setOptions(document.getElementById("skill-filter"), options.skills || [], "Any skill");
  setOptions(document.getElementById("industry-filter"), options.industries || [], "Any industry");
}

async function loadJobs(reset = false) {
  if (reset) { offset = 0; jobs = []; list.innerHTML = ""; }
  status.textContent = "Loading jobs…";
  const response = await fetch(`/api/public/jobs/search?${queryParameters()}`);
  if (!response.ok) { status.textContent = "Jobs could not be loaded."; return; }
  const result = await response.json();
  jobs.push(...result.items);
  total = result.total;
  offset = jobs.length;
  render();
}

async function loadFacets() {
  const response = await fetch(`/api/public/jobs/facets?country=${countryFilter.value}`);
  if (!response.ok) return;
  const facets = await response.json();
  Object.entries(facets).forEach(([key, count]) => {
    const target = document.querySelector(`[data-facet="${key}"]`);
    if (target) target.textContent = count ? `· ${count}` : "";
  });
}

function openFilters() {
  filtersModal.classList.add("open");
  filtersModal.setAttribute("aria-hidden", "false");
}

function closeFilters() {
  filtersModal.classList.remove("open");
  filtersModal.setAttribute("aria-hidden", "true");
}

function closeIntro() {
  introModal.classList.remove("open");
  introModal.setAttribute("aria-hidden", "true");
}

function openIntro() {
  introModal.classList.add("open");
  introModal.setAttribute("aria-hidden", "false");
}

function resetMoreFilters() {
  Object.values(filterIds).forEach(id => { document.getElementById(id).value = ""; });
}

countryFilter.addEventListener("change", () => {
  history.replaceState(null, "", `${location.pathname}?country=${countryFilter.value}`);
  loadFacets();
  loadFilterOptions().then(() => loadJobs(true));
});
[sourceFilter, companyFilter, seniorityFilter, sortFilter].forEach(element => element.addEventListener("change", () => loadJobs(true)));
searchFilter.addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => loadJobs(true), 300);
});
loadMore.addEventListener("click", () => loadJobs());
document.getElementById("clear-filters").addEventListener("click", () => {
  searchFilter.value = ""; sourceFilter.value = ""; companyFilter.value = ""; seniorityFilter.value = ""; sortFilter.value = "date";
  resetMoreFilters(); loadJobs(true);
});
document.getElementById("more-filters").addEventListener("click", openFilters);
document.getElementById("close-filters").addEventListener("click", closeFilters);
document.getElementById("apply-filters").addEventListener("click", () => { closeFilters(); loadJobs(true); });
document.getElementById("reset-more-filters").addEventListener("click", resetMoreFilters);
document.getElementById("catalog-filter-chips").addEventListener("click", event => {
  const button = event.target.closest("[data-clear-filter]");
  if (!button) return;
  document.getElementById(button.dataset.clearFilter).value = "";
  loadJobs(true);
});
filtersModal.addEventListener("click", event => { if (event.target === filtersModal) closeFilters(); });
document.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;
  closeFilters(); closeIntro();
  document.querySelectorAll("details.nav-menu[open]").forEach(menu => menu.removeAttribute("open"));
});
document.addEventListener("click", event => {
  document.querySelectorAll("details.nav-menu[open]").forEach(menu => {
    if (!menu.contains(event.target)) menu.removeAttribute("open");
  });
});
document.getElementById("close-intro").addEventListener("click", closeIntro);
document.getElementById("start-browsing").addEventListener("click", closeIntro);
document.getElementById("catalog-about").addEventListener("click", () => {
  document.querySelectorAll("details.nav-menu[open]").forEach(menu => menu.removeAttribute("open"));
  openIntro();
});
introModal.addEventListener("click", event => { if (event.target === introModal) closeIntro(); });
document.getElementById("catalog-theme-toggle").addEventListener("click", () => {
  const root = document.documentElement;
  const current = root.getAttribute("data-theme") || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  root.setAttribute("data-theme", current === "dark" ? "light" : "dark");
  localStorage.setItem("jobagent-theme", root.getAttribute("data-theme"));
});
list.addEventListener("click", event => {
  const descriptionButton = event.target.closest("[data-description]");
  if (descriptionButton) {
    document.getElementById(`desc-${descriptionButton.dataset.description}`)?.classList.toggle("open");
    descriptionButton.classList.toggle("open");
    return;
  }
  const filterButton = event.target.closest("[data-filter]");
  if (!filterButton) return;
  const type = filterButton.dataset.filter;
  const value = filterButton.dataset.value;
  if (type === "company") companyFilter.value = value;
  else if (type === "source") sourceFilter.value = value;
  else if (type === "seniority") seniorityFilter.value = value.toLowerCase();
  else if (filterIds[type]) document.getElementById(filterIds[type]).value = value;
  else searchFilter.value = value;
  loadJobs(true);
});

loadJobs(true);
loadFacets();
loadFilterOptions();
if (!sessionStorage.getItem("jobagent-catalog-intro-seen")) {
  openIntro();
  sessionStorage.setItem("jobagent-catalog-intro-seen", "1");
}
