const technology = document.body.dataset.technology;
const countryFilter = document.getElementById("country-filter");
const sourceFilter = document.getElementById("source-filter");
const seniorityFilter = document.getElementById("seniority-filter");
const sortFilter = document.getElementById("sort-filter");
const searchFilter = document.getElementById("search-filter");
const list = document.getElementById("job-list");
const status = document.getElementById("catalog-status");
const loadMore = document.getElementById("load-more");
const registerPersonalize = document.getElementById("register-personalize");
const pageSize = 100;
let offset = 0;
let jobs = [];

const params = new URLSearchParams(location.search);
countryFilter.value = params.get("country") === "BG" ? "BG" : "PL";

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

function tag(label, kind = "", query = label) {
  return `<button type="button" class="b ${kind}" data-search="${escapeHtml(query)}">${escapeHtml(label)}</button>`;
}

function renderJob(job) {
  const data = facts(job);
  const stack = [...new Set([...(data.stack || []), ...(job.technologies || [])])].slice(0, 8);
  const work = data.hybrid === true ? "Hybrid" : "Remote";
  const badges = [
    tag(work, "key", work),
    data.seniority && data.seniority !== "unknown" ? tag(data.seniority[0].toUpperCase() + data.seniority.slice(1)) : "",
    data.company_type && data.company_type !== "unknown" ? tag(data.company_type) : "",
    data.product_vs_outsourcing && data.product_vs_outsourcing !== "unknown" ? tag(data.product_vs_outsourcing) : "",
    ...stack.map(item => tag(item, "stack")),
  ].filter(Boolean).join("");
  const sources = (job.sources || []).map(item => `<span class="src-badge">${escapeHtml(item)}</span>`).join("");
  const eligibilityTitle = job.eligibility_confidence === "high"
    ? "Explicit location eligibility found in source data or the job description."
    : "Eligibility is based on the remote region stated in the posting.";
  const description = job.description
    ? `<button type="button" class="disc-toggle" data-description="${escapeHtml(job.id)}">Description <span aria-hidden="true">⌄</span></button>
       <div class="desc-body" id="desc-${escapeHtml(job.id)}">${escapeHtml(job.description)}</div>`
    : "";

  return `<article class="job" id="card-${escapeHtml(job.id)}">
    <div class="stripe"></div>
    <div class="job-body">
      <div class="job-top">
        <div class="job-head">
          <a class="job-title" href="${safeUrl(job.url)}" target="_blank" rel="noopener nofollow">${escapeHtml(job.title)}</a>
          <div class="job-meta">
            <button type="button" class="co" data-search="${escapeHtml(job.company || "")}">${escapeHtml(job.company || "Employer unavailable")}</button>
            <span class="loc">⌖ ${escapeHtml(job.location || "Remote")}</span>${sources}
          </div>
        </div>
        <span class="eligibility" title="${escapeHtml(eligibilityTitle)}">Eligible from ${workLabel()}</span>
      </div>
      <div class="badges">${badges}</div>
      ${(data.summary || job.excerpt) ? `<p class="verdict">${escapeHtml(data.summary || job.excerpt)}${!data.summary && job.excerpt.length >= 320 ? "…" : ""}</p>` : ""}
      ${description ? `<div class="disclosures">${description}</div>` : ""}
      <div class="job-foot"><span class="status-tag new">New</span><span class="job-date">${formatDate(job.posted_at || job.created_at)}</span><a class="view-job" href="${safeUrl(job.url)}" target="_blank" rel="noopener nofollow">View original ↗</a></div>
    </div>
  </article>`;
}

function filteredJobs() {
  const query = searchFilter.value.trim().toLowerCase();
  const source = sourceFilter.value;
  const seniority = seniorityFilter.value;
  const result = jobs.filter(job => {
    const data = facts(job);
    const haystack = [job.title, job.company, job.location, job.description, ...(data.stack || [])].join(" ").toLowerCase();
    return (!query || haystack.includes(query))
      && (!source || (job.sources || []).includes(source))
      && (!seniority || data.seniority === seniority || data.seniority_min === seniority || data.seniority_max === seniority);
  });
  result.sort((a, b) => {
    if (sortFilter.value === "company") return (a.company || "").localeCompare(b.company || "");
    if (sortFilter.value === "title") return a.title.localeCompare(b.title);
    return new Date(b.posted_at || b.created_at) - new Date(a.posted_at || a.created_at);
  });
  return result;
}

function render() {
  const visible = filteredJobs();
  list.innerHTML = visible.map(renderJob).join("");
  document.getElementById("catalog-count").textContent = visible.length;
  status.textContent = visible.length ? `Showing ${visible.length} loaded jobs` : "No current jobs match these filters.";
}

function updateSources() {
  const selected = sourceFilter.value;
  const sources = [...new Set(jobs.flatMap(job => job.sources || []))].sort();
  sourceFilter.innerHTML = '<option value="">All sources</option>' + sources.map(source => `<option value="${escapeHtml(source)}">${escapeHtml(source)}</option>`).join("");
  if (sources.includes(selected)) sourceFilter.value = selected;
}

function updateRegistrationLink() {
  if (!registerPersonalize) return;
  const next = `/jobs/${technology}?country=${countryFilter.value}`;
  registerPersonalize.href = `/register?next=${encodeURIComponent(next)}`;
}

async function loadJobs(reset = false) {
  if (reset) { offset = 0; jobs = []; list.innerHTML = ""; }
  status.textContent = "Loading jobs…";
  const response = await fetch(`/api/public/jobs?technology=${technology}&country=${countryFilter.value}&limit=${pageSize}&offset=${offset}`);
  if (!response.ok) { status.textContent = "Jobs could not be loaded."; return; }
  const batch = await response.json();
  jobs.push(...batch);
  offset += batch.length;
  updateSources();
  render();
  loadMore.hidden = batch.length < pageSize;
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

countryFilter.addEventListener("change", () => {
  history.replaceState(null, "", `${location.pathname}?country=${countryFilter.value}`);
  loadJobs(true); loadFacets(); updateRegistrationLink();
});
[sourceFilter, seniorityFilter, sortFilter].forEach(element => element.addEventListener("change", render));
searchFilter.addEventListener("input", render);
loadMore.addEventListener("click", () => loadJobs());
document.getElementById("clear-filters").addEventListener("click", () => {
  searchFilter.value = ""; sourceFilter.value = ""; seniorityFilter.value = ""; sortFilter.value = "date"; render();
});
list.addEventListener("click", event => {
  const descriptionButton = event.target.closest("[data-description]");
  if (descriptionButton) {
    document.getElementById(`desc-${descriptionButton.dataset.description}`)?.classList.toggle("open");
    descriptionButton.classList.toggle("open");
    return;
  }
  const searchButton = event.target.closest("[data-search]");
  if (searchButton) { searchFilter.value = searchButton.dataset.search; render(); }
});

document.getElementById("personalize-button")?.addEventListener("click", async event => {
  event.currentTarget.disabled = true;
  const response = await fetch("/api/public/jobs/personalize", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ technology, country: countryFilter.value }),
  });
  if (response.ok) {
    const result = await response.json();
    event.currentTarget.textContent = `Added ${result.attached} jobs`;
    window.setTimeout(() => { location.href = "/preferences"; }, 900);
  } else {
    event.currentTarget.disabled = false;
    status.textContent = "Jobs could not be added to your account.";
  }
});

loadJobs(true);
loadFacets();
updateRegistrationLink();
