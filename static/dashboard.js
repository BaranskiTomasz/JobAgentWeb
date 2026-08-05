let ALL_JOBS = [];
let currentStatus = 'new';

let _renderedCount = 0;
const BATCH_SIZE = 25;
let _lazyJobs = [];

let _selectMode = false;
let _selected = new Set();

let _badgeFilters = new Set();

let _availableSources = [];
let _sourcesMap = {};

let _breakdownCache = {};
let _dismissedLoaded = new Set();

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// For interpolating into a single-quoted JS string literal inside an onclick="..." attribute:
// escape backslashes/quotes for JS first, then HTML-escape the result for the attribute.
function escJs(s) {
  return esc(String(s ?? '').replace(/\\/g, '\\\\').replace(/'/g, "\\'"));
}

function safeUrl(u) {
  return (typeof u === 'string' && u.startsWith('http')) ? u : '#';
}

function formatDate(d) {
  if (!d) return '';
  return new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2500);
}

// ── Theme ──────────────────────────────────────────────────────────────────────

function toggleTheme() {
  const root = document.documentElement;
  const current = root.getAttribute('data-theme') ||
    (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const next = current === 'dark' ? 'light' : 'dark';
  root.setAttribute('data-theme', next);
  localStorage.setItem('jobagent-theme', next);
}

(function initTheme() {
  const saved = localStorage.getItem('jobagent-theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
})();

// ── Structured data helpers ────────────────────────────────────────────────────

function _parseStructured(j) {
  if (!j.structured_data) return null;
  try { return typeof j.structured_data === 'string' ? JSON.parse(j.structured_data) : j.structured_data; }
  catch { return null; }
}

function _parseBreakdown(j) {
  if (!j.score_breakdown) return null;
  try { return typeof j.score_breakdown === 'string' ? JSON.parse(j.score_breakdown) : j.score_breakdown; }
  catch { return null; }
}

function _workType(s) {
  if (!s) return null;
  if (s.hybrid) return 'hybrid';
  if (s.remote) return 'remote';
  if (s.remote === false && s.hybrid === false) return 'onsite';
  return null;
}

// Remote job locations are free text like "Warszawa, Poland (Remote)" or bare
// "Poland (Remote)", grouping by the raw string would split the same country
// across every city that ever posted a remote role there. Derive an actual
// country label so "Warszawa, Poland (Remote)" and "Kraków, Poland (Remote)"
// both collapse to "Poland" and match a "Poland" filter.
const _US_STATE_CODES = new Set(['AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA','KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY','DC']);
const _CA_PROVINCE_CODES = new Set(['AB','BC','MB','NB','NL','NS','NT','NU','ON','PE','QC','SK','YT']);

// Only labels that are actually a country (or a well-known multi-country recruiting
// region) are allowed through, otherwise metro/region names with no comma-separated
// country ("Cracow Metropolitan Area", "Greater Sankt Polten") would be mistaken for one.
const _KNOWN_COUNTRIES = new Set([
  'Afghanistan','Albania','Algeria','Andorra','Angola','Argentina','Armenia','Australia','Austria','Azerbaijan',
  'Bahamas','Bahrain','Bangladesh','Barbados','Belarus','Belgium','Belize','Benin','Bhutan','Bolivia',
  'Bosnia and Herzegovina','Botswana','Brazil','Brunei','Bulgaria','Burkina Faso','Burundi',
  'Cambodia','Cameroon','Canada','Cape Verde','Central African Republic','Chad','Chile','China','Colombia','Comoros',
  'Costa Rica','Croatia','Cuba','Cyprus','Czech Republic','Czechia',
  'Democratic Republic of the Congo','Denmark','Djibouti','Dominica','Dominican Republic',
  'Ecuador','Egypt','El Salvador','Equatorial Guinea','Eritrea','Estonia','Eswatini','Ethiopia',
  'Fiji','Finland','France',
  'Gabon','Gambia','Georgia','Germany','Ghana','Greece','Grenada','Guatemala','Guinea','Guinea-Bissau','Guyana',
  'Haiti','Honduras','Hungary',
  'Iceland','India','Indonesia','Iran','Iraq','Ireland','Israel','Italy','Ivory Coast',
  'Jamaica','Japan','Jordan',
  'Kazakhstan','Kenya','Kiribati','Kosovo','Kuwait','Kyrgyzstan',
  'Laos','Latvia','Lebanon','Lesotho','Liberia','Libya','Liechtenstein','Lithuania','Luxembourg',
  'Madagascar','Malawi','Malaysia','Maldives','Mali','Malta','Mauritania','Mauritius','Mexico','Micronesia','Moldova','Monaco','Mongolia','Montenegro','Morocco','Mozambique','Myanmar',
  'Namibia','Nauru','Nepal','Netherlands','New Zealand','Nicaragua','Niger','Nigeria','North Korea','North Macedonia','Norway',
  'Oman',
  'Pakistan','Palau','Palestine','Panama','Papua New Guinea','Paraguay','Peru','Philippines','Poland','Portugal',
  'Qatar',
  'Republic of the Congo','Romania','Russia','Rwanda',
  'Saint Kitts and Nevis','Saint Lucia','Saint Vincent and the Grenadines','Samoa','San Marino','Sao Tome and Principe','Saudi Arabia','Senegal','Serbia','Seychelles','Sierra Leone','Singapore','Slovakia','Slovenia','Solomon Islands','Somalia','South Africa','South Korea','South Sudan','Spain','Sri Lanka','Sudan','Suriname','Sweden','Switzerland','Syria',
  'Taiwan','Tajikistan','Tanzania','Thailand','Timor-Leste','Togo','Tonga','Trinidad and Tobago','Tunisia','Turkey','Turkmenistan','Tuvalu',
  'Uganda','Ukraine','United Arab Emirates','United Kingdom','United States','Uruguay','Uzbekistan',
  'Vanuatu','Vatican City','Venezuela','Vietnam',
  'Yemen',
  'Zambia','Zimbabwe',
]);
const _KNOWN_REGIONS = new Set(['EMEA','NAMER','LATAM','APAC','DACH','European Union','European Economic Area','Benelux','Nordics','Scandinavia','Middle East']);

function _countryOf(location) {
  if (!location) return null;
  const s = String(location).replace(/\s*\(\s*remote\s*\)\s*$/i, '').replace(/\s*\/\s*remote\s*$/i, '').trim();
  if (!s) return null;
  const parts = s.split(',').map(p => p.trim()).filter(Boolean);
  if (!parts.length) return null;
  let candidate = parts[parts.length - 1];
  const code = candidate.toUpperCase();
  if (_US_STATE_CODES.has(code)) candidate = 'United States';
  else if (_CA_PROVINCE_CODES.has(code)) candidate = 'Canada';
  return (_KNOWN_COUNTRIES.has(candidate) || _KNOWN_REGIONS.has(candidate)) ? candidate : null;
}

// Whether a job is remote for Cities-vs-Countries grouping purposes is decided from the
// location text itself ("... (Remote)" / ".../Remote"), not from structured_data.remote,
// many jobs have no structured_data yet (extraction hasn't run or failed on them), and
// those would otherwise silently fall back into "Cities" even though the location text
// plainly says Remote.
function _isRemoteLocationText(location) {
  return /\(\s*remote\s*\)\s*$/i.test(location || '') || /\/\s*remote\s*$/i.test(location || '');
}

const _WORK_LABEL = { remote: 'Remote', hybrid: 'Hybrid', onsite: 'On-site' };
const _SENIORITY_VALUES = ['junior', 'mid', 'senior', 'lead', 'director'];
const _CTYPE_VALUES = ['startup', 'scaleup', 'enterprise', 'agency'];
const _PVO_VALUES = ['product', 'outsourcing', 'mixed'];
const _SUBSCORE_LABELS = { stack_fit: 'Stack', seniority_fit: 'Seniority', company_fit: 'Company', compensation_fit: 'Salary' };

function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

// If the session expired mid-use, every API call starts 401ing, send the
// user back to /login instead of leaving the dashboard silently broken.
function _redirectIfUnauthenticated(resp) {
  if (resp.status === 401) { location.href = '/login'; return true; }
  return false;
}

// ── Stats / summary band ───────────────────────────────────────────────────────

async function loadStats() {
  let r, s;
  try {
    r = await fetch('/api/jobs/stats');
    if (_redirectIfUnauthenticated(r)) return;
    s = await r.json();
  } catch {
    return;
  }
  document.getElementById('f-new').textContent      = s.new;
  document.getElementById('f-reviewed').textContent = s.reviewed;
  document.getElementById('f-applied').textContent  = s.applied;
  document.getElementById('f-rejected').textContent = s.rejected;
  document.getElementById('f-auto').textContent     = s.auto_rejected;

  document.getElementById('t-new').textContent      = s.new;
  document.getElementById('t-reviewed').textContent = s.reviewed;
  document.getElementById('t-applied').textContent  = s.applied;
  document.getElementById('t-rejected').textContent = s.rejected;
  document.getElementById('t-auto').textContent      = s.auto_rejected;
  document.getElementById('t-all').textContent      = s.total;

  document.getElementById('s-avg-new').textContent = s.avg_score_new != null ? s.avg_score_new.toFixed(1) : '—';

  const lastRun = s.last_run
    ? new Date(s.last_run.replace(' ', 'T') + 'Z').toLocaleString('pl-PL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
    : 'never';
  document.getElementById('last-run').textContent = 'last run ' + lastRun;

  loadCalibSummary();
  loadCost();
}

// Looks up one bucket's apply-rate by its range label. apply_rate_by_bucket is
// absent until JobAgentWeb is redeployed with it (see routers/evaluation.py),
// this null-guards the same way the old precision_at_5/10 lookups always did.
function _bucketRate(data, range) {
  const b = (data.apply_rate_by_bucket || []).find(x => x.range === range);
  return b && b.apply_rate != null ? Math.round(b.apply_rate * 100) + '%' : '—';
}

async function loadCalibSummary() {
  let d;
  try {
    const r = await fetch('/api/eval/report');
    if (_redirectIfUnauthenticated(r)) return;
    d = await r.json();
  } catch {
    return;
  }
  document.getElementById('calib-b1').textContent = _bucketRate(d, '1-5');
  document.getElementById('calib-b2').textContent = _bucketRate(d, '6-10');
  document.getElementById('calib-div-count').textContent = (d.divergence_cases || []).length;
}

async function loadCost() {
  let u;
  try {
    const r = await fetch('/api/usage/summary');
    if (_redirectIfUnauthenticated(r)) return;
    u = await r.json();
  } catch {
    return;
  }
  document.getElementById('cost-per100').textContent = u.cost_per_100_usd != null ? `$${u.cost_per_100_usd.toFixed(2)}` : '—';
  document.getElementById('cost-today').textContent  = u.today_cost_usd != null ? `$${u.today_cost_usd.toFixed(3)}` : '—';
  document.getElementById('cost-total').textContent  = u.total_cost_usd != null ? `$${u.total_cost_usd.toFixed(2)}` : '—';
}

// ── Preference profile / "what the agent learned" (read-only) ─────────────────

function _humanDim(dim) { return String(dim || '').replace(/_/g, ' '); }
function _humanValue(v) { return v ? String(v).replace(/_/g, ' ') : ''; }

const _SIGNAL_TAG_LABEL = { ACCEPT: 'Likes', REJECT: 'Avoids', INFER: 'Inferred', NEUTRAL: 'No signal' };
const _SIGNAL_TAG_CLASS = { ACCEPT: 'acc', REJECT: 'rej', INFER: 'inf', NEUTRAL: 'neu' };

function _signalMainText(s) {
  if (s.note) return s.note;
  const val = _humanValue(s.value);
  const dim = _humanDim(s.dim);
  if (s.type === 'NEUTRAL') return `No clear pattern yet on ${dim}.`;
  if (s.type === 'INFER') return `Likely prefers ${dim}${val ? ': ' + val : ''}, based on limited evidence.`;
  return `${s.type === 'ACCEPT' ? 'Favors' : 'Avoids'} ${dim}${val ? ': ' + val : ''}.`;
}

function _signalMetaText(s) {
  const parts = [_humanDim(s.dim) + (s.value ? ': ' + _humanValue(s.value) : '')];
  if (s.conf) parts.push(s.conf.toLowerCase() + ' confidence');
  if (s.n_match != null && s.n_total != null) parts.push(`${s.n_match}/${s.n_total} examples`);
  else if (s.n_total != null) parts.push(`from ${s.n_total} examples`);
  return parts.join(' · ');
}

function _renderSignalChips(signals) {
  const notable = (signals || []).filter(s => s.type === 'ACCEPT' || s.type === 'REJECT' || s.type === 'INFER').slice(0, 6);
  if (!notable.length) return '<span class="lc-empty">No strong signals yet, apply/reject a few more jobs, then distill locally.</span>';
  return notable.map(s => {
    const cls = _SIGNAL_TAG_CLASS[s.type] || 'inf';
    return `<div class="sig"><span class="tag ${cls}">${_SIGNAL_TAG_LABEL[s.type] || s.type}</span><span class="txt">${esc(_signalMainText(s))}</span></div>`;
  }).join('');
}

function _renderSignalList(signals) {
  if (!signals || !signals.length) return '';
  return `<div class="pref-list">${signals.map(s => {
    const cls = _SIGNAL_TAG_CLASS[s.type] || 'inf';
    const neutralCls = s.type === 'NEUTRAL' ? ' neutral' : '';
    return `
      <div class="pref-row${neutralCls}">
        <span class="pref-tag ${cls}">${_SIGNAL_TAG_LABEL[s.type] || s.type}</span>
        <div class="pref-body">
          <div class="pref-main">${esc(_signalMainText(s))}</div>
          <div class="pref-meta">${esc(_signalMetaText(s))}</div>
        </div>
      </div>`;
  }).join('')}</div>`;
}

async function _loadLearnedCard() {
  const el = document.getElementById('lc-signals');
  try {
    const r = await fetch('/api/preference-profile');
    if (_redirectIfUnauthenticated(r)) return;
    const d = await r.json();
    if (!d.profile) { el.innerHTML = '<span class="lc-empty">No profile yet, run distillation locally in JobAgent.</span>'; return; }
    if (!d.profile.signals || !d.profile.signals.length) { el.innerHTML = '<span class="lc-empty">' + esc((d.profile.content || '').slice(0, 200)) + '…</span>'; return; }
    el.innerHTML = _renderSignalChips(d.profile.signals);
  } catch {
    el.innerHTML = '<span class="lc-empty">Error loading profile.</span>';
  }
}

function openLearnedModal() {
  document.getElementById('learned-modal').classList.add('open');
  _loadLearnedFull();
}
function closeLearnedModal() { document.getElementById('learned-modal').classList.remove('open'); }

async function _loadLearnedFull() {
  const meta = document.getElementById('learned-meta');
  const full = document.getElementById('learned-full');
  try {
    const r = await fetch('/api/preference-profile');
    const d = await r.json();
    if (!d.profile) { meta.textContent = ''; full.textContent = 'No profile yet. Run distillation locally in JobAgent.'; return; }
    const p = d.profile;
    const updated = new Date(p.updated_at.replace(' ', 'T') + 'Z').toLocaleString('pl-PL', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    meta.innerHTML = `<span>Applied: ${p.applied_count}</span><span>Rejected: ${p.rejected_count}</span><span>Updated: ${updated}</span>`;
    full.innerHTML = (p.signals && p.signals.length) ? _renderSignalList(p.signals) : esc(p.content);
  } catch {
    full.textContent = 'Error loading profile.';
  }
}

// ── Eval / Calibration modal ────────────────────────────────────────────────────

async function openEvalModal() {
  document.getElementById('eval-modal').classList.add('open');
  document.getElementById('eval-body').innerHTML = '<p>Loading…</p>';

  let data;
  try {
    const r = await fetch('/api/eval/report');
    data = await r.json();
  } catch {
    document.getElementById('eval-body').innerHTML = '<p>Failed to load report.</p>';
    return;
  }

  const cases = data.divergence_cases || [];
  const rows = cases.map(c => `
    <tr>
      <td><span class="kind ${c.divergence_type === 'false_positive' ? 'fp' : 'fn'}"><span class="dt"></span>${c.divergence_type === 'false_positive' ? 'Overrated' : 'Underrated'}</span></td>
      <td>${esc(c.title)}</td>
      <td class="co-cell">${esc(c.company)}</td>
      <td class="rk">${c.listwise_rank != null ? `#${c.listwise_rank}` : '—'}</td>
    </tr>`).join('');

  const wa = data.would_apply || {};
  const waPrecisionPct = wa.precision != null ? Math.round(wa.precision * 100) : null;
  const waMeetsGate = waPrecisionPct != null && waPrecisionPct >= 90;

  document.getElementById('eval-body').innerHTML = `
    <div class="eval-metrics">
      <div class="eval-metric"><div class="ev">${_bucketRate(data, '1-5')}</div><div class="el">RANK 1-5</div></div>
      <div class="eval-metric"><div class="ev">${_bucketRate(data, '6-10')}</div><div class="el">RANK 6-10</div></div>
      <div class="eval-metric"><div class="ev">${_bucketRate(data, '11-15')}</div><div class="el">RANK 11-15</div></div>
      <div class="eval-metric"><div class="ev">${_bucketRate(data, '16-20')}</div><div class="el">RANK 16-20</div></div>
    </div>
    <p class="eval-ranked-line">${data.total_ranked ?? 0} jobs ranked total &middot; ${cases.length} divergence cases</p>
    <p class="calib-explain"><b>Apply-rate by rank bucket</b> looks at every job you've actually <i>decided</i> on (applied, rejected, or auto-rejected) and groups it by the listwise rank it was given, then shows what fraction of each group you applied to. Unlike a fixed top-K snapshot, this uses your <i>entire</i> decision history at each rank range, so it sharpens as you decide on more jobs instead of staying pinned to the same handful. "Reviewed" doesn't count as a decision: it means you looked but haven't committed either way, so it's left out entirely.
    <br><br>A well-calibrated ranking shows apply-rate falling as rank worsens (highest at 1-5, lowest at 16-20). A flat or inverted pattern means the ranking isn't actually tracking what you apply to.
    <br><br>A <b>divergence case</b> flags a specific miss: a job ranked in the top 5 that you rejected (the model overrated it), or ranked #16+ that you applied to anyway (the model underrated it). These are the same cases JobAgent feeds back into its own scoring as calibration examples, so the model doesn't repeat the same mistake.</p>

    <div class="wa-gate ${waMeetsGate ? 'met' : ''}">
      <div class="wa-gate-hd">
        <span class="wa-gate-title">Would-apply gate</span>
        <span class="wa-gate-pct">${waPrecisionPct != null ? waPrecisionPct + '%' : '—'} <span class="wa-gate-target">/ 90% target</span></span>
      </div>
      <div class="wa-gate-bar"><div class="wa-gate-fill" style="width:${waPrecisionPct != null ? Math.min(100, waPrecisionPct) : 0}%"></div></div>
      <div class="wa-gate-detail">${wa.flagged_total ?? 0} flagged &middot; ${wa.decided ?? 0} decided (${wa.applied ?? 0} applied, ${wa.rejected ?? 0} rejected) &middot; ${(wa.flagged_total ?? 0) - (wa.decided ?? 0)} still open</div>
      <p class="calib-explain">Of the jobs flagged as <b>"would apply"</b> (score ≥ ${data.would_apply_score_floor ?? 7.0}, no dealbreaker risk), what fraction were actually applied to once decided.</p>
    </div>

    <div class="eval-tbl-h">Divergence cases <span class="cnt">(${cases.length})</span></div>
    <div class="div-scroll">
      <table class="div-tbl">
        <thead><tr><th>Type</th><th>Title</th><th>Company</th><th>Rank</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="4" class="div-empty">No divergence cases yet.</td></tr>'}</tbody>
      </table>
    </div>`;
}
function closeEvalModal() { document.getElementById('eval-modal').classList.remove('open'); }

// ── Status filter (funnel + tabs share one source of truth) ───────────────────

function setStatusFilter(status) {
  currentStatus = status;
  document.querySelectorAll('.tab[data-status]').forEach(t => t.classList.toggle('active', t.dataset.status === status));
  document.querySelectorAll('.funnel .step[data-status]').forEach(s => s.classList.toggle('active', s.dataset.status === status));
  loadJobs();
}

document.querySelectorAll('.tab[data-status]').forEach(tab => {
  tab.addEventListener('click', () => setStatusFilter(tab.dataset.status));
});
document.querySelectorAll('.funnel .step[data-status]').forEach(step => {
  step.addEventListener('click', () => setStatusFilter(step.dataset.status));
});

// ── Sources / jobs loading ─────────────────────────────────────────────────────

async function _loadSources() {
  // Never let this block the initial jobs load, a failure here shouldn't leave
  // the dashboard looking empty just because the source dropdown didn't populate.
  try {
    const r = await fetch('/api/sources');
    if (_redirectIfUnauthenticated(r)) return;
    const sources = await r.json();
    if (!Array.isArray(sources)) return;
    _availableSources = sources;
    _sourcesMap = Object.fromEntries(_availableSources.map(s => [s.id, s.name]));

    const sel = document.getElementById('source-filter');
    while (sel.options.length > 1) sel.remove(1);
    _availableSources.forEach(s => sel.add(new Option(s.name, s.id)));
  } catch {
    // ignored, source dropdown just stays at "All sources"
  }
}

async function loadJobs() {
  const query = document.getElementById('search').value;
  const source = document.getElementById('source-filter').value;
  const params = new URLSearchParams({ status: currentStatus });
  if (query) params.set('query', query);
  if (source) params.set('source', source);

  try {
    const r = await fetch('/api/jobs?' + params);
    if (_redirectIfUnauthenticated(r)) return;
    ALL_JOBS = await r.json();
  } catch {
    showToast('Failed to load jobs, is the server running?');
    return;
  }
  render();
}

// ── Card rendering ──────────────────────────────────────────────────────────────

function _renderBadges(j, s) {
  const on = f => _badgeFilters.has(f) ? ' on' : '';
  const tags = [];

  const work = _workType(s);
  if (work) tags.push(`<span class="b key${on('work=' + work)}" onclick="toggleBadgeFilter('work=${work}')"><span class="dotmark"></span>${_WORK_LABEL[work]}</span>`);

  if (s && s.seniority && s.seniority !== 'unknown')
    tags.push(`<span class="b${on('seniority=' + s.seniority)}" onclick="toggleBadgeFilter('${escJs('seniority=' + s.seniority)}')">${esc(cap(s.seniority))}</span>`);
  if (s && s.company_type && s.company_type !== 'unknown')
    tags.push(`<span class="b${on('ctype=' + s.company_type)}" onclick="toggleBadgeFilter('${escJs('ctype=' + s.company_type)}')">${esc(cap(s.company_type))}</span>`);
  if (s && s.product_vs_outsourcing && s.product_vs_outsourcing !== 'unknown')
    tags.push(`<span class="b${on('pvo=' + s.product_vs_outsourcing)}" onclick="toggleBadgeFilter('${escJs('pvo=' + s.product_vs_outsourcing)}')">${esc(cap(s.product_vs_outsourcing))}</span>`);
  (s && s.stack || []).slice(0, 6).forEach(t => {
    const key = 'stack=' + t.toLowerCase();
    tags.push(`<span class="b stack${on(key)}" onclick="toggleBadgeFilter('${escJs(key)}')">${esc(t)}</span>`);
  });

  return tags.length ? `<div class="badges">${tags.join('')}</div>` : '';
}

function _renderSecondOpinion(j) {
  if (!j.debate_note) return '';
  const flag = j.debate_flag || '';
  const cls = flag === 'dealbreaker_risk' ? 'dealbreaker' : (flag === 'underrated' ? 'underrated' : '');
  return `
    <div class="second ${cls}">
      <span class="glyph"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg></span>
      <div class="so-body">
        <div class="so-label">Second opinion <span class="so-flag">${esc(flag.replace(/_/g, ' '))}</span></div>
        <div class="so-note">${esc(j.debate_note)}</div>
      </div>
    </div>`;
}

function _scoreItemLi(jobId, type, idx, text) {
  const icon = type === 'pro'
    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>';
  const key = `${jobId}:${type}:${idx}`;
  return `
    <li class="score-item" id="si-${esc(key)}">
      ${icon}<span class="txt">${esc(text)}</span>
      <button type="button" class="dismiss-x" onclick="toggleDismissPop('${escJs(jobId)}','${type}',${idx})" title="Not relevant to me">×</button>
      <div class="dismiss-pop" id="dp-${esc(key)}">
        <input type="text" id="dp-input-${esc(key)}" placeholder="Why doesn't this matter to you?"
               onkeydown="if(event.key==='Enter') confirmDismiss('${escJs(jobId)}','${type}',${idx}); if(event.key==='Escape') toggleDismissPop('${escJs(jobId)}','${type}',${idx})">
        <button type="button" class="go" onclick="confirmDismiss('${escJs(jobId)}','${type}',${idx})">Save</button>
        <button type="button" class="cancel" onclick="toggleDismissPop('${escJs(jobId)}','${type}',${idx})">Cancel</button>
      </div>
    </li>`;
}

function _renderBreakdownSection(jobId, b) {
  if (!b || (!(b.pros || []).length && !(b.cons || []).length && !Object.keys(b.sub_scores || {}).length)) return '';
  _breakdownCache[jobId] = b;
  // Fresh DOM for this job means any earlier "already loaded" dismissed-state fetch
  // no longer applies to what's on screen now, force a re-fetch next time it's opened.
  _dismissedLoaded.delete(jobId);
  const subs = Object.entries(b.sub_scores || {}).map(([key, val]) => `
    <div class="ss">
      <span class="lab">${esc(_SUBSCORE_LABELS[key] || key)}</span>
      <div class="track"><div class="fill" style="width:${Math.max(0, Math.min(100, (val / 10) * 100))}%"></div></div>
      <span class="val">${esc(String(val))}</span>
    </div>`).join('');
  const pros = (b.pros || []).map((p, i) => _scoreItemLi(jobId, 'pro', i, p)).join('');
  const cons = (b.cons || []).map((c, i) => _scoreItemLi(jobId, 'con', i, c)).join('');

  return `
    <button type="button" class="disc-toggle" id="disc-bd-${esc(jobId)}" onclick="toggleBreakdown('${esc(jobId)}')">
      <svg class="di" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 3v18M4 8l5-5 5 5"/></svg>
      Why this score <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
    </button>
    <div class="breakdown" id="bd-${esc(jobId)}">
      <div class="bd-grid">
        <div>
          <div class="bd-h">Sub-scores</div>
          <div class="subscores">${subs || '<span class="pc-empty">No sub-scores recorded.</span>'}</div>
        </div>
        <div class="proscons">
          <div>
            <div class="bd-h">Pros</div>
            <ul class="pc-list pros">${pros || '<span class="pc-empty">None noted.</span>'}</ul>
          </div>
          <div>
            <div class="bd-h">Cons</div>
            <ul class="pc-list cons">${cons || '<span class="pc-empty">None noted.</span>'}</ul>
          </div>
        </div>
      </div>
    </div>`;
}

function _renderCard(j) {
  const s = _parseStructured(j);
  const on = f => _badgeFilters.has(f) ? ' on' : '';
  const score = j.score != null ? j.score.toFixed(1) : '—';
  const meterPct = j.score != null ? Math.max(0, Math.min(100, (j.score / 10) * 100)) : 0;
  const rankBadge = j.listwise_rank != null ? `<div class="rank-badge">#${j.listwise_rank}</div>` : '';
  // JobAgent's ranker/exploration.py prefixes rank_reason with "[EXPLORATION] "
  // for jobs randomly sampled from outside the top-ranked pool for a full AI
  // review (see JobAgent's routers/evaluation.py apply-rate-by-bucket, which
  // excludes these from the ranking-quality metric for the same reason: the
  // rank reflects pool composition, not the normal pipeline's judgment).
  // Stripped from the displayed reason and shown as a badge instead of raw
  // bracket text.
  const isExploration = (j.rank_reason || '').startsWith('[EXPLORATION] ');
  const explorationBadge = isExploration
    ? `<div class="exploration-badge" title="Randomly sampled from outside the top-ranked pool for a full AI review, checks whether the ranking is missing good jobs lower down.">
         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M14.5 9.5l-2 5-5 2 2-5 5-2z"/></svg>
         Exploration pick
       </div>`
    : '';
  const wouldApplyBadge = j.would_apply
    ? `<div class="would-apply-badge" title="${esc(j.would_apply_reason || '')}">
         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>
         Would apply
       </div>`
    : '';
  const srcName = _sourcesMap[j.source] || j.source || '';
  const work = _workType(s);
  const locFilterValue = _isRemoteLocationText(j.location) ? (_countryOf(j.location) || j.location || '') : (j.location || '');
  const locFilterKey = 'loc=' + locFilterValue;
  const locLabel = j.location || '—';

  const reason = (j.rank_reason || j.score_reason || '').replace(/^\[EXPLORATION\] /, '');
  let rejNote = null;
  if (j.status === 'rejected' && j.rejection_reason) rejNote = j.rejection_reason;
  else if (j.status === 'auto_rejected' && j.score_reason) rejNote = j.score_reason;

  const breakdown = _renderBreakdownSection(j.id, _parseBreakdown(j));
  const descToggle = j.description
    ? `<button type="button" class="disc-toggle" id="disc-desc-${esc(j.id)}" onclick="toggleDesc('${esc(j.id)}')">
         <svg class="di" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h16M4 12h16M4 18h10"/></svg>
         Description <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
       </button>
       <div class="desc-body" id="desc-${esc(j.id)}">${esc(j.description)}</div>`
    : '';

  return `
  <div class="job st-${esc(j.status)}${j.debate_flag === 'dealbreaker_risk' ? ' demoted' : ''}" id="card-${esc(j.id)}">
    <div class="stripe"></div>
    <div class="job-body">
      <div class="job-top">
        <div class="job-sel"><input type="checkbox" ${_selected.has(j.id) ? 'checked' : ''} onchange="toggleSelect('${esc(j.id)}', this.checked)"></div>
        <div class="job-head">
          <a class="job-title" href="${safeUrl(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>
          <div class="job-meta">
            <button type="button" class="co${on('firm=' + j.company)}" onclick="toggleBadgeFilter('firm=${escJs(j.company || '')}')">${esc(j.company)}</button>
            <button type="button" class="loc${on(locFilterKey)}" onclick="toggleBadgeFilter('${escJs(locFilterKey)}')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 6-9 12-9 12s-9-6-9-12a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
              ${esc(locLabel)}
            </button>
            ${srcName ? `<button type="button" class="src-badge${on('source=' + j.source)}" onclick="toggleBadgeFilter('source=${escJs(j.source)}')">${esc(srcName)}</button>` : ''}
          </div>
        </div>
        <div class="score-block">
          ${wouldApplyBadge}
          ${explorationBadge}
          ${rankBadge}
          <div class="score-meter">
            <div class="score-num">${score}<span class="of">/10</span></div>
            <div class="meter-track"><div class="meter-fill" style="width:${meterPct}%"></div></div>
          </div>
        </div>
      </div>
      ${_renderBadges(j, s)}
      ${reason ? `<div class="verdict">${esc(reason)}</div>` : ''}
      ${_renderSecondOpinion(j)}
      ${rejNote ? `<div class="rejected-note"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>${esc(rejNote)}</div>` : ''}
      ${(breakdown || descToggle) ? `<div class="disclosures">${breakdown}${descToggle}</div>` : ''}
      <div class="job-foot">
        <span class="status-tag ${esc(j.status)}">${esc(j.status.replace('_', ' '))}</span>
        <span class="job-date">${formatDate(j.created_at)}</span>
        <div class="act-group">
          <button type="button" class="act ${j.status === 'reviewed' ? 'on-reviewed' : ''}" onclick="setStatus('${esc(j.id)}', 'reviewed')">Reviewed</button>
          <button type="button" class="act ${j.status === 'applied' ? 'on-applied' : ''}" onclick="setStatus('${esc(j.id)}', 'applied')">Applied ✓</button>
          <button type="button" class="act reject" onclick="toggleRejectPop('${esc(j.id)}')">Reject ✕</button>
        </div>
      </div>
      <div class="reject-pop" id="reject-pop-${esc(j.id)}">
        <input type="text" id="reject-input-${esc(j.id)}" placeholder="Reason, e.g. rate too low, too junior…" value="${esc(j.rejection_reason || '')}"
               onkeydown="if(event.key==='Enter') confirmReject('${esc(j.id)}'); if(event.key==='Escape') toggleRejectPop('${esc(j.id)}')">
        <button type="button" class="go" onclick="confirmReject('${esc(j.id)}')">Reject</button>
        <button type="button" class="cancel" onclick="toggleRejectPop('${esc(j.id)}')">Cancel</button>
      </div>
    </div>
  </div>`;
}

// ── Lazy-loading render ─────────────────────────────────────────────────────────

function render() {
  const sort = document.getElementById('sort').value;
  _lazyJobs = [...ALL_JOBS];
  if (sort === 'rank') {
    _lazyJobs.sort((a, b) => {
      const aRanked = a.listwise_rank != null;
      const bRanked = b.listwise_rank != null;
      if (aRanked && bRanked) return a.listwise_rank - b.listwise_rank;
      if (aRanked !== bRanked) return aRanked ? -1 : 1;
      return (b.score ?? -1) - (a.score ?? -1);
    });
  }
  if (sort === 'score')   _lazyJobs.sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  if (sort === 'date')    _lazyJobs.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  if (sort === 'company') _lazyJobs.sort((a, b) => (a.company || '').localeCompare(b.company || ''));

  if (_badgeFilters.size) _lazyJobs = _lazyJobs.filter(_matchesBadgeFilters);
  _updateFilterBar();
  _updateFilterBadges();

  document.getElementById('count').textContent = `${_lazyJobs.length} job${_lazyJobs.length !== 1 ? 's' : ''}`;
  _renderedCount = 0;

  const container = document.getElementById('jobs-container');
  container.classList.toggle('selecting', _selectMode);
  container.innerHTML = '';

  // Always clear any pager/load-more left over from whatever tab was showing before,
  // it lives as a sibling of #jobs-container, so clearing container.innerHTML above
  // doesn't remove it, and the empty-results branch below used to return before ever
  // reaching _renderPager()'s own cleanup, leaving a stale "Load more" bar on screen.
  const oldPager = document.getElementById('pager-wrap');
  if (oldPager) oldPager.remove();

  if (!_lazyJobs.length) {
    container.innerHTML = `<div class="no-results">${_emptyStateMessage()}</div>`;
    return;
  }

  _appendBatch(container, BATCH_SIZE);
  _renderPager();
}

function _emptyStateMessage() {
  const filtered = _badgeFilters.size || document.getElementById('search').value || document.getElementById('source-filter').value;
  if (filtered) return 'No jobs match the current filters.';
  if (currentStatus === 'new') return 'No new job offers here. Run the agent locally.';
  return 'No jobs found.';
}

function _appendBatch(container, count) {
  const batch = _lazyJobs.slice(_renderedCount, _renderedCount + count);
  _renderedCount += batch.length;

  const frag = document.createDocumentFragment();
  batch.forEach(j => {
    const tmp = document.createElement('div');
    tmp.innerHTML = _renderCard(j).trim();
    frag.appendChild(tmp.firstChild);
  });
  container.appendChild(frag);
}

function _pageNumbers(current, total) {
  const pages = new Set([1, total, current, current - 1, current + 1, current - 2, current + 2]);
  return [...pages].filter(p => p >= 1 && p <= total).sort((a, b) => a - b);
}

function _renderPager() {
  const container = document.getElementById('jobs-container');
  const old = document.getElementById('pager-wrap');
  if (old) old.remove();

  const total = _lazyJobs.length;
  const totalPages = Math.ceil(total / BATCH_SIZE);
  const currentPage = Math.ceil(_renderedCount / BATCH_SIZE);
  if (totalPages <= 1 && _renderedCount >= total) return;

  const wrap = document.createElement('div');
  wrap.id = 'pager-wrap';
  wrap.className = 'load-more-bar';

  let html = '';
  if (_renderedCount < total) {
    const remaining = total - _renderedCount;
    html += `<button type="button" class="load-more-btn" onclick="_loadMore()">Load more (${Math.min(BATCH_SIZE, remaining)} of ${remaining} left)</button>`;
  }

  if (totalPages > 1) {
    const nums = _pageNumbers(currentPage, totalPages);
    let pagerHtml = `<button type="button" class="nav" onclick="_goToPage(1)" ${currentPage <= 1 ? 'disabled' : ''}>&laquo;</button>`;
    let prev = 0;
    for (const p of nums) {
      if (p - prev > 1) pagerHtml += `<span class="ellipsis">…</span>`;
      pagerHtml += `<button type="button" class="${p === currentPage ? 'active' : ''}" onclick="_goToPage(${p})">${p}</button>`;
      prev = p;
    }
    pagerHtml += `<button type="button" class="nav" onclick="_goToPage(${totalPages})" ${currentPage >= totalPages ? 'disabled' : ''}>&raquo;</button>`;
    html += `<div class="pager">${pagerHtml}</div>`;
  }

  wrap.innerHTML = html;
  container.parentElement.appendChild(wrap);
}

function _loadMore() {
  const container = document.getElementById('jobs-container');
  _appendBatch(container, BATCH_SIZE);
  _renderPager();
}

function _goToPage(n) {
  // Numbered page buttons jump straight to that page's own slice, unlike _loadMore(),
  // which appends cumulatively, clicking "8" should show only page 8, not pages 1-8 at once.
  const container = document.getElementById('jobs-container');
  const start = (n - 1) * BATCH_SIZE;
  const end = Math.min(start + BATCH_SIZE, _lazyJobs.length);
  container.innerHTML = '';
  _renderedCount = start;
  _appendBatch(container, end - start);
  _renderPager();
  container.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── Disclosure toggles ─────────────────────────────────────────────────────────

async function toggleBreakdown(jobId) {
  const opening = !document.getElementById(`bd-${jobId}`).classList.contains('open');
  document.getElementById(`bd-${jobId}`).classList.toggle('open');
  document.getElementById(`disc-bd-${jobId}`).classList.toggle('open');
  if (opening && !_dismissedLoaded.has(jobId)) {
    _dismissedLoaded.add(jobId);
    try {
      const r = await fetch(`/api/jobs/${jobId}/dismissed-items`);
      const d = await r.json();
      const b = _breakdownCache[jobId] || {};
      (d.items || []).forEach(it => {
        const idx = (b[it.item_type + 's'] || []).indexOf(it.item_text);
        if (idx !== -1) _markItemDismissed(jobId, it.item_type, idx, it.reason);
      });
    } catch {}
  }
}

// ── Dismiss a pro/con as not relevant ─────────────────────────────────────────

function toggleDismissPop(jobId, type, idx) {
  const key = `${jobId}:${type}:${idx}`;
  document.querySelectorAll('.dismiss-pop.open').forEach(el => { if (el.id !== `dp-${key}`) el.classList.remove('open'); });
  const pop = document.getElementById(`dp-${key}`);
  if (!pop) return;
  pop.classList.toggle('open');
  if (pop.classList.contains('open')) {
    const input = document.getElementById(`dp-input-${key}`);
    input && input.focus();
  }
}

async function confirmDismiss(jobId, type, idx) {
  const key = `${jobId}:${type}:${idx}`;
  const input = document.getElementById(`dp-input-${key}`);
  const reason = input ? input.value.trim() : '';
  if (!reason) { input && input.focus(); return; }

  const b = _breakdownCache[jobId];
  const itemText = b && (b[type + 's'] || [])[idx];
  if (!itemText) return;

  const r = await fetch(`/api/jobs/${jobId}/dismiss-item`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ item_type: type, item_text: itemText, reason }),
  });
  if (!r.ok) { showToast('Failed to save, please try again'); return; }
  _markItemDismissed(jobId, type, idx, reason);
  showToast('Noted, this will shape future scoring, not this job.');
}

function _markItemDismissed(jobId, type, idx, reason) {
  const key = `${jobId}:${type}:${idx}`;
  const li = document.getElementById(`si-${key}`);
  if (!li || li.classList.contains('dismissed')) return;
  li.classList.add('dismissed');
  const pop = document.getElementById(`dp-${key}`);
  if (pop) pop.classList.remove('open');
  const btn = li.querySelector('.dismiss-x');
  if (btn) btn.remove();
  const note = document.createElement('span');
  note.className = 'dismissed-note';
  note.textContent = `Dismissed: ${reason}`;
  li.appendChild(note);
}

function toggleDesc(jobId) {
  document.getElementById(`desc-${jobId}`).classList.toggle('open');
  document.getElementById(`disc-desc-${jobId}`).classList.toggle('open');
}

// ── Reject popover ──────────────────────────────────────────────────────────────

function toggleRejectPop(jobId) {
  document.querySelectorAll('.reject-pop.open').forEach(el => { if (el.id !== `reject-pop-${jobId}`) el.classList.remove('open'); });
  const pop = document.getElementById(`reject-pop-${jobId}`);
  pop.classList.toggle('open');
  if (pop.classList.contains('open')) {
    const input = document.getElementById(`reject-input-${jobId}`);
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }
}

async function confirmReject(jobId) {
  const input = document.getElementById(`reject-input-${jobId}`);
  const reason = input ? input.value.trim() : '';
  await setStatus(jobId, 'rejected', reason);
}

// ── Status update ───────────────────────────────────────────────────────────────

async function setStatus(jobId, status, rejectionReason = null) {
  const body = { status };
  if (status === 'rejected' && rejectionReason !== null) body.rejection_reason = rejectionReason;
  const r = await fetch(`/api/jobs/${jobId}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    showToast('Error saving status, please try again');
    return;
  }

  const job = ALL_JOBS.find(j => j.id === jobId);
  if (job) {
    job.status = status;
    if (status === 'rejected' && rejectionReason !== null) job.rejection_reason = rejectionReason;
  }

  const belongs = currentStatus === 'all' || status === currentStatus;

  if (!belongs) {
    const ai = ALL_JOBS.findIndex(j => j.id === jobId);
    if (ai !== -1) ALL_JOBS.splice(ai, 1);
    const li = _lazyJobs.findIndex(j => j.id === jobId);
    if (li !== -1) _lazyJobs.splice(li, 1);

    const card = document.getElementById(`card-${jobId}`);
    if (card) {
      card.style.transition = 'opacity 0.15s, transform 0.15s';
      card.style.opacity = '0';
      card.style.transform = 'translateX(12px)';
      setTimeout(() => { card.remove(); }, 160);
    }
    document.getElementById('count').textContent = `${_lazyJobs.length} job${_lazyJobs.length !== 1 ? 's' : ''}`;
  } else {
    const card = document.getElementById(`card-${jobId}`);
    if (card && job) {
      const tmp = document.createElement('div');
      tmp.innerHTML = _renderCard(job).trim();
      card.replaceWith(tmp.firstChild);
    }
  }

  loadStats();
  const labels = { reviewed: 'Marked as reviewed', applied: 'Applied ✓', rejected: 'Rejected' };
  showToast(labels[status] || 'Updated');
}

// ── Exact-score filter panel ────────────────────────────────────────────────────

function _scoreKey(score) {
  return score != null ? `score=${score.toFixed(1)}` : 'score=none';
}

function _buildScoreFilterPanel() {
  const panel = document.getElementById('scoref-panel');
  if (!panel) return;
  const counts = new Map();
  for (const j of ALL_JOBS) {
    const key = _scoreKey(j.score);
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  const keys = [...counts.keys()].sort((a, b) => {
    if (a === 'score=none') return 1;
    if (b === 'score=none') return -1;
    return parseFloat(b.slice(6)) - parseFloat(a.slice(6));
  });
  if (!keys.length) {
    panel.innerHTML = '<div class="scoref-hint">No jobs loaded.</div>';
    return;
  }
  const pills = keys.map(key => {
    const isNone = key === 'score=none';
    const label = isNone ? 'n/a' : parseFloat(key.slice(6)).toFixed(1);
    const active = _badgeFilters.has(key) ? ' on' : '';
    return `<span class="spill${active}" onclick="toggleBadgeFilter('${key}')">${label}<span class="n">${counts.get(key)}</span></span>`;
  }).join('');
  panel.innerHTML =
    `<div class="scoref-title">Filter by exact score</div>
     <p class="scoref-hint">Pick one or more values, jobs matching any of them are shown.</p>
     <div class="scoref-grid">${pills}</div>
     <button type="button" class="scoref-clear" onclick="_clearScoreFilters()">Clear score filter</button>`;
}

function _clearScoreFilters() {
  for (const f of [..._badgeFilters]) if (f.startsWith('score=')) _badgeFilters.delete(f);
  _buildScoreFilterPanel();
  render();
}

function toggleScoreFilterPanel(e) {
  e.stopPropagation();
  const panel = document.getElementById('scoref-panel');
  const opening = !panel.classList.contains('open');
  panel.classList.toggle('open', opening);
  if (opening) _buildScoreFilterPanel();
}

document.addEventListener('click', (e) => {
  const wrap = document.querySelector('.scoref');
  const panel = document.getElementById('scoref-panel');
  if (wrap && panel && !wrap.contains(e.target)) panel.classList.remove('open');
});

document.addEventListener('click', (e) => {
  document.querySelectorAll('details.nav-menu[open]').forEach(menu => {
    if (!menu.contains(e.target)) menu.removeAttribute('open');
  });
});
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  document.querySelectorAll('details.nav-menu[open]').forEach(menu => menu.removeAttribute('open'));
});

// ── Badge / dimension filters ───────────────────────────────────────────────────

function _matchesBadgeFilters(j) {
  const active = [..._badgeFilters];
  const scoreFilters = active.filter(f => f.startsWith('score='));
  const otherFilters = active.filter(f => !f.startsWith('score='));

  if (scoreFilters.length && !scoreFilters.includes(_scoreKey(j.score))) return false;
  if (!otherFilters.length) return true;

  const s = _parseStructured(j);
  const stackLower = (s && s.stack || []).map(t => t.toLowerCase());
  const work = _workType(s);
  const locValue = _isRemoteLocationText(j.location) ? (_countryOf(j.location) || j.location || '') : (j.location || '');

  for (const f of otherFilters) {
    if (f.startsWith('work=')      && work !== f.slice(5)) return false;
    if (f.startsWith('seniority=') && (!s || s.seniority !== f.slice(10))) return false;
    if (f.startsWith('ctype=')     && (!s || s.company_type !== f.slice(7))) return false;
    if (f.startsWith('pvo=')       && (!s || s.product_vs_outsourcing !== f.slice(4))) return false;
    if (f.startsWith('stack=')     && !stackLower.includes(f.slice(6))) return false;
    if (f.startsWith('source=')    && j.source !== f.slice(7)) return false;
    if (f.startsWith('firm=')      && (j.company || '') !== f.slice(5)) return false;
    if (f.startsWith('loc=')       && locValue !== f.slice(4)) return false;
  }
  return true;
}

function toggleBadgeFilter(f) {
  _badgeFilters.has(f) ? _badgeFilters.delete(f) : _badgeFilters.add(f);
  if (f.startsWith('score=')) _buildScoreFilterPanel();
  render();
}

function removeBadgeFilter(f) {
  _badgeFilters.delete(f);
  if (f.startsWith('score=')) _buildScoreFilterPanel();
  render();
}

function clearBadgeFilters() {
  _badgeFilters.clear();
  _buildScoreFilterPanel();
  render();
  if (document.getElementById('filters-modal').classList.contains('open')) _buildFiltersModal();
}

function _filterLabel(f) {
  if (f.startsWith('score=')) return f.slice(6) === 'none' ? 'score: not scored' : `score: ${f.slice(6)}`;
  if (f.startsWith('work='))      return f.slice(5);
  if (f.startsWith('seniority=')) return f.slice(10);
  if (f.startsWith('ctype='))     return f.slice(7);
  if (f.startsWith('pvo='))       return f.slice(4);
  if (f.startsWith('stack='))     return f.slice(6);
  if (f.startsWith('source='))    return _sourcesMap[f.slice(7)] || f.slice(7);
  if (f.startsWith('firm='))      return f.slice(5);
  if (f.startsWith('loc='))       return f.slice(4);
  return f;
}

function _updateFilterBar() {
  const bar = document.getElementById('filter-bar');
  const chips = document.getElementById('filter-chips');
  if (!bar || !chips) return;
  bar.classList.toggle('on', _badgeFilters.size > 0);
  chips.innerHTML = [..._badgeFilters].map(f =>
    `<span class="fchip">${esc(_filterLabel(f))}<button onclick="removeBadgeFilter('${escJs(f)}')" title="Remove">×</button></span>`
  ).join('');
}

function _updateFilterBadges() {
  const scoreN = [..._badgeFilters].filter(f => f.startsWith('score=')).length;
  const otherN = _badgeFilters.size - scoreN;
  const scoreBadge = document.getElementById('scoref-badge');
  const moreBadge  = document.getElementById('more-filters-badge');
  if (scoreBadge) { scoreBadge.textContent = scoreN; scoreBadge.classList.toggle('on', scoreN > 0); }
  if (moreBadge)  { moreBadge.textContent  = otherN; moreBadge.classList.toggle('on', otherN > 0); }
  document.getElementById('scoref-btn').classList.toggle('on', scoreN > 0);
  document.getElementById('more-filters-btn').classList.toggle('on', otherN > 0);
}

// ── All-filters modal ────────────────────────────────────────────────────────────

function _fchip(key, label, mono = false) {
  const on = _badgeFilters.has(key) ? ' on' : '';
  return `<button type="button" class="fchip-toggle${mono ? ' mono' : ''}${on}" onclick="toggleBadgeFilter('${escJs(key)}'); _buildFiltersModal()">${esc(label)}</button>`;
}

function _buildFiltersModal() {
  const body = document.getElementById('filters-body');
  if (!body) return;

  const cities = new Set();
  const countries = new Set();
  ALL_JOBS.forEach(j => {
    if (!j.location) return;
    if (_isRemoteLocationText(j.location)) {
      const country = _countryOf(j.location);
      if (country) countries.add(country);
    } else {
      cities.add(j.location);
    }
  });

  body.innerHTML = `
    <div class="fgroup">
      <div class="fgroup-h">Work type</div>
      <div class="fmodal-grid">${['remote', 'hybrid', 'onsite'].map(w => _fchip('work=' + w, _WORK_LABEL[w])).join('')}</div>
    </div>
    <div class="fgroup">
      <div class="fgroup-h">Seniority</div>
      <div class="fmodal-grid">${_SENIORITY_VALUES.map(v => _fchip('seniority=' + v, cap(v))).join('')}</div>
    </div>
    <div class="fgroup">
      <div class="fgroup-h">Company type</div>
      <div class="fmodal-grid">${_CTYPE_VALUES.map(v => _fchip('ctype=' + v, cap(v))).join('')}</div>
    </div>
    <div class="fgroup">
      <div class="fgroup-h">Product vs. outsourcing</div>
      <div class="fmodal-grid">${_PVO_VALUES.map(v => _fchip('pvo=' + v, cap(v))).join('')}</div>
    </div>
    <div class="fgroup">
      <div class="fgroup-h">Source</div>
      <div class="fmodal-grid">${_availableSources.map(src => _fchip('source=' + src.id, src.name)).join('')}</div>
    </div>
    <div class="fgroup">
      <div class="fgroup-h">Cities</div>
      <p class="fgroup-note">Only applies to hybrid and on-site postings.</p>
      <div class="fmodal-grid">${[...cities].sort().map(c => _fchip('loc=' + c, c)).join('') || '<span class="fgroup-note">None yet.</span>'}</div>
    </div>
    <div class="fgroup">
      <div class="fgroup-h">Countries</div>
      <p class="fgroup-note">Only applies to remote postings.</p>
      <div class="fmodal-grid">${[...countries].sort().map(c => _fchip('loc=' + c, c)).join('') || '<span class="fgroup-note">None yet.</span>'}</div>
    </div>
  `;
}

function openFiltersModal() {
  document.getElementById('filters-modal').classList.add('open');
  _buildFiltersModal();
}
function closeFiltersModal() { document.getElementById('filters-modal').classList.remove('open'); }

// ── Select mode & bulk actions ──────────────────────────────────────────────────

function toggleSelectMode() {
  _selectMode = !_selectMode;
  if (!_selectMode) _selected.clear();
  const btn = document.getElementById('select-toggle');
  if (btn) { btn.textContent = _selectMode ? 'Cancel' : 'Select'; btn.classList.toggle('on', _selectMode); }
  const bar = document.getElementById('bulk-bar');
  if (bar) bar.classList.toggle('on', _selectMode);
  render();
}

function toggleSelect(jobId, checked) {
  checked ? _selected.add(jobId) : _selected.delete(jobId);
  _updateBulkBar();
}

function selectAll() {
  _lazyJobs.forEach(j => _selected.add(j.id));
  document.querySelectorAll('#jobs-container .job-sel input').forEach(cb => { cb.checked = true; });
  _updateBulkBar();
}

function deselectAll() {
  _selected.clear();
  document.querySelectorAll('#jobs-container .job-sel input').forEach(cb => { cb.checked = false; });
  _updateBulkBar();
}

function _updateBulkBar() {
  const n = _selected.size;
  const el = document.getElementById('bulk-count');
  if (el) el.textContent = `${n} selected`;
  document.querySelectorAll('.bulk-act').forEach(btn => { btn.disabled = n === 0; });
}

async function bulkSetStatus(status, reason = '') {
  const ids = [..._selected];
  if (!ids.length) return;
  await Promise.all(ids.map(id =>
    fetch(`/api/jobs/${id}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status, ...(reason ? { rejection_reason: reason } : {}) }),
    })
  ));
  ids.forEach(id => {
    const job = ALL_JOBS.find(j => j.id === id);
    if (job) { job.status = status; if (reason) job.rejection_reason = reason; }
  });
  _selected.clear();
  _updateBulkBar();
  render();
  loadStats();
}

function openBulkRejectModal() {
  if (!_selected.size) return;
  const msg = document.getElementById('bulk-reject-msg');
  if (msg) msg.textContent = `Rejecting ${_selected.size} job${_selected.size > 1 ? 's' : ''}.`;
  const input = document.getElementById('bulk-reject-reason');
  if (input) input.value = '';
  document.getElementById('bulk-reject-modal').classList.add('open');
  setTimeout(() => input && input.focus(), 50);
}
function closeBulkRejectModal() { document.getElementById('bulk-reject-modal').classList.remove('open'); }
function confirmBulkReject() {
  const reason = (document.getElementById('bulk-reject-reason')?.value || '').trim();
  closeBulkRejectModal();
  bulkSetStatus('rejected', reason);
}

// ── Search / sort listeners ──────────────────────────────────────────────────────

let searchTimeout;
document.getElementById('search').addEventListener('input', () => {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(loadJobs, 300);
});
document.getElementById('source-filter').addEventListener('change', loadJobs);
document.getElementById('sort').addEventListener('change', render);

// ── Init ──────────────────────────────────────────────────────────────────────

loadStats();
_loadSources().then(loadJobs);
_loadLearnedCard();
