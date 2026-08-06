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

const COUNTRY_GROUPS = {
  EU: [
    'Austria', 'Belgium', 'Bulgaria', 'Croatia', 'Cyprus', 'Czechia', 'Denmark', 'Estonia',
    'Finland', 'France', 'Germany', 'Greece', 'Hungary', 'Ireland', 'Italy', 'Latvia',
    'Lithuania', 'Luxembourg', 'Malta', 'Netherlands', 'Poland', 'Portugal', 'Romania',
    'Slovakia', 'Slovenia', 'Spain', 'Sweden',
  ],
  EUROZONE: [
    'Austria', 'Belgium', 'Croatia', 'Cyprus', 'Estonia', 'Finland', 'France', 'Germany',
    'Greece', 'Ireland', 'Italy', 'Latvia', 'Lithuania', 'Luxembourg', 'Malta', 'Netherlands',
    'Portugal', 'Slovakia', 'Slovenia', 'Spain',
  ],
  NATO: [
    'Albania', 'Belgium', 'Bulgaria', 'Canada', 'Croatia', 'Czechia', 'Denmark', 'Estonia',
    'Finland', 'France', 'Germany', 'Greece', 'Hungary', 'Iceland', 'Italy', 'Latvia',
    'Lithuania', 'Luxembourg', 'Montenegro', 'Netherlands', 'North Macedonia', 'Norway',
    'Poland', 'Portugal', 'Romania', 'Slovakia', 'Slovenia', 'Spain', 'Sweden', 'Turkey',
    'United Kingdom', 'United States',
  ],
};

// Adds every country in the named group that isn't already a chip. Does not
// remove or track anything, so the button always means "make sure this whole
// group is present right now," even if some of it was removed earlier.
function addCountryGroup(groupName) {
  const existing = new Set(getChipValues('country-chips').map(v => v.toLowerCase()));
  (COUNTRY_GROUPS[groupName] || []).forEach(country => {
    if (!existing.has(country.toLowerCase())) addChipValue('country-chips', country);
  });
}

const CITY_SUGGESTIONS = [
  'Warsaw', 'Kraków', 'Wrocław', 'Gdańsk', 'Poznań', 'Łódź', 'Katowice', 'Szczecin',
  'Berlin', 'Munich', 'Hamburg', 'Frankfurt', 'Cologne', 'Stuttgart',
  'London', 'Manchester', 'Edinburgh', 'Bristol',
  'Amsterdam', 'Rotterdam', 'The Hague', 'Utrecht',
  'Paris', 'Lyon', 'Marseille', 'Toulouse',
  'Madrid', 'Barcelona', 'Valencia', 'Lisbon', 'Porto',
  'Milan', 'Rome', 'Turin',
  'Dublin', 'Cork',
  'Brussels', 'Antwerp',
  'Zurich', 'Geneva', 'Basel',
  'Vienna', 'Graz',
  'Stockholm', 'Gothenburg', 'Copenhagen', 'Oslo', 'Helsinki',
  'Prague', 'Brno', 'Bratislava', 'Budapest', 'Bucharest', 'Sofia', 'Zagreb', 'Ljubljana',
  'Athens', 'Vilnius', 'Riga', 'Tallinn', 'Kyiv',
  'New York', 'San Francisco', 'Austin', 'Boston', 'Seattle', 'Chicago', 'Toronto', 'Vancouver',
  'Dubai', 'Tel Aviv', 'Istanbul', 'Bangalore', 'Singapore', 'Tokyo', 'Seoul',
  'Sydney', 'Melbourne',
];

function toggle(el) { el.classList.toggle('on'); }

function toggleWorkMode(el) {
  el.classList.toggle('on');
  updateWorkModePanels();
}

function updateWorkModePanels() {
  const remote = document.querySelector('#workmode-group [data-value="remote"]').classList.contains('on');
  const hybridOrOnsite = document.querySelector('#workmode-group [data-value="hybrid"]').classList.contains('on')
    || document.querySelector('#workmode-group [data-value="onsite"]').classList.contains('on');
  document.getElementById('remote-panel').style.display = remote ? '' : 'none';
  document.getElementById('hybrid-panel').style.display = hybridOrOnsite ? '' : 'none';
}

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

async function savePreferences() {
  const btn = document.getElementById('save-btn');
  const status = document.getElementById('save-status');
  btn.disabled = true;
  status.classList.remove('is-error');
  status.textContent = 'Saving…';

  const salaryMin = document.getElementById('salary-min').value;

  const fields = {
    work_mode: getToggledValues('workmode-group'),
    remote_countries: getChipValues('country-chips'),
    hybrid_cities: getChipValues('city-chips'),
    salary_min: salaryMin ? parseInt(salaryMin, 10) : null,
    salary_currency: document.getElementById('salary-currency').value,
    show_jobs_without_salary: document.getElementById('show-no-salary').checked ? 1 : 0,
    seniority_levels: getToggledValues('seniority-group'),
    role_types: getToggledValues('role-group'),
    preferred_company_types: getToggledValues('company-group'),
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
  populateDatalist('city-suggestions', CITY_SUGGESTIONS);
  populateDatalist('language-suggestions', LANGUAGE_SUGGESTIONS);

  Object.entries(COUNTRY_GROUPS).forEach(([name, countries]) => {
    const tip = document.getElementById(`tip-${name}`);
    if (tip) tip.textContent = countries.join(', ');
  });

  const [cv, prefs] = await Promise.all([
    fetchOrNull('/api/cv-profiles/active'),
    fetchOrNull('/api/candidate-preferences/active'),
  ]);

  if (cv) {
    _activeCvProfileId = cv.id;
    document.getElementById('cv-filename').textContent = cv.filename;
  }

  setToggled('workmode-group', prefs ? prefs.work_mode : ['remote']);
  (prefs ? prefs.remote_countries : []).forEach(c => addChipValue('country-chips', c));
  (prefs ? prefs.hybrid_cities : []).forEach(c => addChipValue('city-chips', c));
  updateWorkModePanels();

  if (prefs) {
    if (prefs.salary_min != null) document.getElementById('salary-min').value = prefs.salary_min;
    if (prefs.salary_currency) document.getElementById('salary-currency').value = prefs.salary_currency;
    document.getElementById('show-no-salary').checked = !!prefs.show_jobs_without_salary;
  }

  setToggled('seniority-group', prefs ? prefs.seniority_levels : []);
  setToggled('role-group', prefs ? prefs.role_types : []);
  setToggled('company-group', prefs ? prefs.preferred_company_types : []);

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
