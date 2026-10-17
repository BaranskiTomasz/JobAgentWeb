function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

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

function _renderSignalGroup(container, signals) {
  if (!signals.length) {
    container.innerHTML = '<span class="lc-empty">None yet.</span>';
    return;
  }
  container.innerHTML = `<div class="pref-list">${signals.map(s => {
    const cls = _SIGNAL_TAG_CLASS[s.type] || 'inf';
    const neutralCls = s.type === 'NEUTRAL' ? ' neutral' : '';
    return `<div class="pref-row${neutralCls}">
      <span class="pref-tag ${cls}">${_SIGNAL_TAG_LABEL[s.type] || s.type}</span>
      <div class="pref-body">
        <div class="pref-main">${esc(_signalMainText(s))}</div>
        <div class="pref-meta">${esc(_signalMetaText(s))}</div>
      </div>
    </div>`;
  }).join('')}</div>`;
}

function _redirectIfUnauthenticated(resp) {
  if (resp.status === 401) { location.href = '/login'; return true; }
  return false;
}

async function _loadPreferenceProfile() {
  const meta = document.getElementById('pp-meta');
  const groups = {
    ACCEPT: document.getElementById('pp-accept'),
    REJECT: document.getElementById('pp-reject'),
    INFER: document.getElementById('pp-infer'),
    NEUTRAL: document.getElementById('pp-neutral'),
  };
  try {
    const r = await fetch('/api/preference-profile');
    if (_redirectIfUnauthenticated(r)) return;
    const d = await r.json();
    if (!d.profile) {
      meta.textContent = 'No profile yet, run distillation locally in JobAgent.';
      Object.values(groups).forEach(container => { container.innerHTML = '<span class="lc-empty">No profile yet.</span>'; });
      return;
    }
    const p = d.profile;
    const updated = new Date(p.updated_at.replace(' ', 'T') + 'Z').toLocaleString('pl-PL', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    meta.innerHTML = `<span>Applied: ${p.applied_count}</span><span>Rejected: ${p.rejected_count}</span><span>Updated: ${updated}</span>`;
    if (!p.signals || !p.signals.length) {
      // Legacy profiles (content_format != 'json') carry free text in p.content instead.
      groups.ACCEPT.innerHTML = p.content ? `<p>${esc(p.content)}</p>` : '<span class="lc-empty">None yet.</span>';
      groups.REJECT.innerHTML = groups.INFER.innerHTML = groups.NEUTRAL.innerHTML = '<span class="lc-empty">None yet.</span>';
      return;
    }
    const signals = { ACCEPT: [], REJECT: [], INFER: [], NEUTRAL: [] };
    p.signals.forEach(signal => {
      if (signals[signal.type]) signals[signal.type].push(signal);
    });
    Object.entries(groups).forEach(([type, container]) => _renderSignalGroup(container, signals[type]));
  } catch {
    meta.textContent = 'Error loading profile.';
  }
}

_loadPreferenceProfile();
