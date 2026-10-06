const body = document.body;
const technology = body.dataset.technology;
const countryFilter = document.getElementById("country-filter");
const list = document.getElementById("job-list");
const status = document.getElementById("catalog-status");
const loadMore = document.getElementById("load-more");
const registerPersonalize = document.getElementById("register-personalize");
const pageSize = 30;
let offset = 0;

const params = new URLSearchParams(location.search);
countryFilter.value = params.get("country") === "BG" ? "BG" : "PL";

function updateRegistrationLink() {
  if (!registerPersonalize) return;
  const next = `/jobs/${technology}?country=${countryFilter.value}`;
  registerPersonalize.href = `/register?next=${encodeURIComponent(next)}`;
}

function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = value || "";
  return node.innerHTML;
}

function formatDate(value) {
  if (!value) return "data nieznana";
  return new Intl.DateTimeFormat("pl-PL", { dateStyle: "medium" }).format(new Date(value));
}

function renderJob(job) {
  const sources = job.sources.map(source => `<span>${escapeHtml(source)}</span>`).join("");
  const technologies = job.technologies.map(item => `<span>${escapeHtml(item)}</span>`).join("");
  const countryName = countryFilter.value === "PL" ? "Polski" : "Bułgarii";
  const eligibility = job.eligibility_confidence === "high" ? `Dostępna z ${countryName}` : `Prawdopodobnie dostępna z ${countryName}`;
  return `<article class="job-card">
    <h2><a href="${escapeHtml(job.url)}" target="_blank" rel="noopener nofollow">${escapeHtml(job.title)}</a></h2>
    <div class="job-meta"><span>${escapeHtml(job.company || "Firma nieznana")}</span><span>${escapeHtml(job.location || "Remote")}</span><span>${formatDate(job.posted_at || job.created_at)}</span><span class="confidence">${eligibility}</span></div>
    ${job.excerpt ? `<p class="job-excerpt">${escapeHtml(job.excerpt)}…</p>` : ""}
    <div class="job-tags">${technologies}${sources}</div>
  </article>`;
}

async function loadJobs(reset = false) {
  if (reset) {
    offset = 0;
    list.innerHTML = "";
  }
  status.textContent = "Ładowanie ofert…";
  const response = await fetch(`/api/public/jobs?technology=${technology}&country=${countryFilter.value}&limit=${pageSize}&offset=${offset}`);
  if (!response.ok) {
    status.textContent = "Nie udało się pobrać ofert.";
    return;
  }
  const jobs = await response.json();
  list.insertAdjacentHTML("beforeend", jobs.map(renderJob).join(""));
  offset += jobs.length;
  status.textContent = offset ? `Wyświetlono ${offset} ofert` : "Brak aktualnych ofert dla tych filtrów.";
  loadMore.hidden = jobs.length < pageSize;
}

async function loadFacets() {
  const response = await fetch(`/api/public/jobs/facets?country=${countryFilter.value}`);
  if (!response.ok) return;
  const facets = await response.json();
  Object.entries(facets).forEach(([key, count]) => {
    const target = document.querySelector(`[data-facet="${key}"]`);
    if (target) target.textContent = count;
  });
}

countryFilter.addEventListener("change", () => {
  history.replaceState(null, "", `${location.pathname}?country=${countryFilter.value}`);
  loadJobs(true);
  loadFacets();
  updateRegistrationLink();
});
loadMore.addEventListener("click", () => loadJobs());

document.getElementById("personalize-button")?.addEventListener("click", async event => {
  event.currentTarget.disabled = true;
  const response = await fetch("/api/public/jobs/personalize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ technology, country: countryFilter.value }),
  });
  if (response.ok) {
    const result = await response.json();
    event.currentTarget.textContent = `Dodano ${result.attached} ofert`;
    window.setTimeout(() => { location.href = "/preferences"; }, 900);
  } else {
    event.currentTarget.disabled = false;
    status.textContent = "Nie udało się dodać ofert do konta.";
  }
});

loadJobs(true);
loadFacets();
updateRegistrationLink();
