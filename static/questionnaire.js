// Matches every language the collector's language filter
// (collector/language_filter.py, JobAgent repo) can actually detect,
// suggesting a language it can't recognize would be misleading.
const LANGUAGE_SUGGESTIONS = [
  'English', 'Polish', 'German', 'French', 'Spanish', 'Italian', 'Portuguese', 'Dutch',
  'Russian', 'Ukrainian', 'Czech', 'Slovak', 'Romanian', 'Bulgarian', 'Croatian', 'Slovenian',
  'Hungarian', 'Greek', 'Swedish', 'Norwegian', 'Danish', 'Finnish', 'Estonian', 'Latvian',
  'Lithuanian', 'Turkish', 'Arabic', 'Hebrew', 'Persian', 'Hindi', 'Bengali', 'Urdu',
  'Chinese (Simplified)', 'Chinese (Traditional)', 'Japanese', 'Korean', 'Vietnamese',
  'Thai', 'Indonesian', 'Tagalog', 'Swahili', 'Afrikaans', 'Welsh', 'Catalan', 'Albanian',
  'Macedonian', 'Somali',
];
const LEVEL_OPTIONS = ['Native', 'C2', 'C1', 'B2', 'B1', 'A2', 'A1'];

const COUNTRY_SUGGESTIONS = [
  'Poland', 'Germany', 'United Kingdom', 'Netherlands', 'France', 'Spain', 'Portugal', 'Italy',
  'Ireland', 'Belgium', 'Switzerland', 'Austria', 'Sweden', 'Norway', 'Denmark', 'Finland',
  'Czechia', 'Slovakia', 'Hungary', 'Romania', 'Bulgaria', 'Croatia', 'Slovenia', 'Greece',
  'Estonia', 'Latvia', 'Lithuania', 'Ukraine', 'Serbia', 'Iceland', 'Luxembourg', 'Malta',
  'Cyprus', 'United States', 'Canada', 'Mexico', 'Brazil', 'Argentina', 'Chile', 'Colombia',
  'United Arab Emirates', 'Israel', 'Turkey', 'India', 'Singapore', 'Japan', 'South Korea',
  'Australia', 'New Zealand', 'South Africa', 'Egypt', 'Morocco',
];

function toggle(el) { el.classList.toggle('on'); }

function makeRemovableChip(value) {
  const chip = document.createElement('span');
  chip.className = 'chip removable on';
  chip.dataset.value = value;
  chip.appendChild(document.createTextNode(value + ' '));
  const x = document.createElement('span');
  x.className = 'x';
  x.textContent = '✕';
  x.onclick = (e) => { e.stopPropagation(); chip.remove(); };
  chip.appendChild(x);
  return chip;
}

function addChipValue(containerId, value) {
  if (!value) return;
  document.getElementById(containerId).appendChild(makeRemovableChip(value));
}

function addChip(containerId, inputId) {
  const input = document.getElementById(inputId);
  const val = input.value.trim();
  if (!val) return;
  addChipValue(containerId, val);
  input.value = '';
  input.focus();
}

function getChipValues(containerId) {
  return Array.from(document.querySelectorAll(`#${containerId} .chip`)).map(c => c.dataset.value);
}

function getToggledValues(containerId) {
  return Array.from(document.querySelectorAll(`#${containerId} .chip.on`)).map(c => c.dataset.value);
}

function setToggled(containerId, values) {
  const set = new Set(values || []);
  document.querySelectorAll(`#${containerId} .chip`).forEach(c => {
    c.classList.toggle('on', set.has(c.dataset.value));
  });
}

function makeLangRow(language, level) {
  const row = document.createElement('div');
  row.className = 'lang-row';

  const langInput = document.createElement('input');
  langInput.type = 'text';
  langInput.className = 'lang-input';
  langInput.setAttribute('list', 'language-suggestions');
  langInput.placeholder = 'Language, e.g. English';
  langInput.value = language ? language.replace(/\b\w/g, c => c.toUpperCase()) : '';

  const levelSelect = document.createElement('select');
  levelSelect.className = 'level-select';
  LEVEL_OPTIONS.forEach(opt => {
    const o = document.createElement('option');
    o.value = opt;
    o.textContent = opt;
    if (opt === (level || 'B2')) o.selected = true;
    levelSelect.appendChild(o);
  });

  const removeBtn = document.createElement('button');
  removeBtn.className = 'btn-add';
  removeBtn.type = 'button';
  removeBtn.textContent = 'Remove';
  removeBtn.onclick = () => row.remove();

  row.appendChild(langInput);
  row.appendChild(levelSelect);
  row.appendChild(removeBtn);
  return row;
}

function addLangRow(language, level) {
  document.getElementById('lang-rows').appendChild(makeLangRow(language, level));
}

function getLanguages() {
  return Array.from(document.querySelectorAll('#lang-rows .lang-row'))
    .map(row => ({
      language: row.querySelector('.lang-input').value.trim().toLowerCase(),
      level: row.querySelector('.level-select').value,
    }))
    .filter(l => l.language);
}

let _activeCvProfileId = null;
let _activePrefs = null;

async function savePreferences() {
  const btn = document.getElementById('save-btn');
  const status = document.getElementById('save-status');
  btn.disabled = true;
  status.classList.remove('is-error');
  status.textContent = 'Saving…';

  const salaryMin = document.getElementById('salary-min').value;
  const seniorityLevels = getToggledValues('seniority-group');
  const companyTypes = getToggledValues('company-group');

  const fields = {
    work_mode: ['remote'],
    // This form has no control for remote_countries (a candidate's full
    // acceptable-remote-markets list, used by evaluator/dealbreakers.py's geo
    // check) - only the legacy single work_country field. Carrying the
    // existing value forward avoids silently wiping it on every save, since
    // the backend's insert() writes a brand-new row with any omitted field
    // defaulting to null.
    remote_countries: _activePrefs ? (_activePrefs.remote_countries || []) : [],
    work_country: document.getElementById('work-country').value.trim(),
    salary_min: salaryMin ? parseInt(salaryMin, 10) : null,
    salary_currency: document.getElementById('salary-currency').value,
    show_jobs_without_salary: document.getElementById('show-no-salary').checked ? 1 : 0,
    seniority_levels: seniorityLevels,
    required_seniority_levels: document.getElementById('seniority-hard').checked ? seniorityLevels : [],
    role_types: getToggledValues('role-group'),
    preferred_company_types: companyTypes,
    required_company_types: document.getElementById('company-hard').checked ? companyTypes : [],
    extra_tech: getChipValues('tech-chips'),
    avoided_tech: getChipValues('avoid-chips'),
    languages: getLanguages(),
    open_notes: document.getElementById('notes').value.trim(),
  };

  try {
    const res = await fetch('/api/candidate-preferences', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cv_profile_id: _activeCvProfileId, fields }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Save failed');
    status.textContent = 'Saved.';
  } catch (err) {
    status.textContent = err.message;
    status.classList.add('is-error');
  } finally {
    btn.disabled = false;
  }
}

function populateDatalist(datalistId, values) {
  const datalist = document.getElementById(datalistId);
  values.forEach(v => {
    const option = document.createElement('option');
    option.value = v;
    datalist.appendChild(option);
  });
}

async function fetchOrNull(url) {
  const res = await fetch(url);
  if (!res.ok) return null;
  return res.json();
}

async function init() {
  populateDatalist('country-suggestions', COUNTRY_SUGGESTIONS);
  populateDatalist('language-suggestions', LANGUAGE_SUGGESTIONS);

  const [cv, prefs] = await Promise.all([
    fetchOrNull('/api/cv-profiles/active'),
    fetchOrNull('/api/candidate-preferences/active'),
  ]);

  if (cv) {
    _activeCvProfileId = cv.id;
    document.getElementById('cv-filename').textContent = cv.filename;
  }

  _activePrefs = prefs;

  const legacyWorkCountry = prefs && (prefs.remote_countries || []).length === 1 ? prefs.remote_countries[0] : '';
  document.getElementById('work-country').value = prefs ? (prefs.work_country || legacyWorkCountry) : '';

  if (prefs) {
    if (prefs.salary_min != null) document.getElementById('salary-min').value = prefs.salary_min;
    if (prefs.salary_currency) document.getElementById('salary-currency').value = prefs.salary_currency;
    document.getElementById('show-no-salary').checked = !!prefs.show_jobs_without_salary;
  }

  setToggled('seniority-group', prefs ? prefs.seniority_levels : []);
  document.getElementById('seniority-hard').checked = !!(prefs && (prefs.required_seniority_levels || []).length);
  setToggled('role-group', prefs ? prefs.role_types : []);
  setToggled('company-group', prefs ? prefs.preferred_company_types : []);
  document.getElementById('company-hard').checked = !!(prefs && (prefs.required_company_types || []).length);

  (prefs ? (prefs.extra_tech || []) : []).forEach(t => addChipValue('tech-chips', t));
  (prefs ? (prefs.avoided_tech || []) : []).forEach(t => addChipValue('avoid-chips', t));

  const languages = prefs ? (prefs.languages || []) : [];
  if (languages.length) {
    languages.forEach(l => addLangRow(l.language, l.level));
  } else {
    addLangRow('english', 'B2');
  }

  if (prefs && prefs.open_notes) document.getElementById('notes').value = prefs.open_notes;
}

init();
