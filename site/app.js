const DATA_URL = '../data/videos.json';
const STORE_KEY = 'football-hub:v1';

const state = {
  data: null,
  selectedTeams: new Set(),
  selectedSources: new Set(),
  favoritesOnly: false,
  unseenOnly: false,
  search: '',
  seen: new Set(),
  theme: 'light'
};

const $ = (s) => document.querySelector(s);

function loadStore() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY) || '{}');
    if (Array.isArray(saved.selectedTeams)) state.selectedTeams = new Set(saved.selectedTeams);
    if (Array.isArray(saved.selectedSources)) state.selectedSources = new Set(saved.selectedSources);
    if (Array.isArray(saved.seen)) state.seen = new Set(saved.seen);
    state.favoritesOnly = Boolean(saved.favoritesOnly);
    state.unseenOnly = Boolean(saved.unseenOnly);
    state.theme = saved.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  } catch (_) {}
  applyTheme();
}

function saveStore() {
  localStorage.setItem(STORE_KEY, JSON.stringify({
    selectedTeams: [...state.selectedTeams],
    selectedSources: [...state.selectedSources],
    seen: [...state.seen],
    favoritesOnly: state.favoritesOnly,
    unseenOnly: state.unseenOnly,
    theme: state.theme
  }));
}

function applyTheme() {
  document.documentElement.dataset.theme = state.theme;
  $('#themeBtn').textContent = state.theme === 'dark' ? '☾' : '☼';
}

function formatDate(value) {
  if (!value) return 'Date inconnue';
  const d = new Date(value);
  const now = Date.now();
  const delta = Math.max(0, now - d.getTime());
  const minute = 60_000, hour = 60 * minute, day = 24 * hour;
  if (delta < minute) return 'à l’instant';
  if (delta < hour) return `il y a ${Math.floor(delta / minute)} min`;
  if (delta < day) return `il y a ${Math.floor(delta / hour)} h`;
  if (delta < 7 * day) return `il y a ${Math.floor(delta / day)} j`;
  return new Intl.DateTimeFormat('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' }).format(d);
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
}

function renderStats() {
  const d = state.data;
  const videos = d?.videos || [];
  const unseen = videos.filter(v => !state.seen.has(v.id)).length;
  $('#stats').innerHTML = `
    <div class="stat"><div class="stat-value">${videos.length}</div><div class="stat-label">résumés conservés</div></div>
    <div class="stat"><div class="stat-value">${unseen}</div><div class="stat-label">nouveaux pour toi</div></div>
  `;
}

function renderChips() {
  const d = state.data;
  const teams = d.teams || collectTeams(d.videos || []);
  const sources = collectSources(d.videos || [], d.source_status || []);
  $('#teamChips').innerHTML = teams.map(t => `
    <button class="chip ${state.selectedTeams.has(t.id) ? 'active' : ''}" data-team="${escapeHtml(t.id)}">${escapeHtml(t.name)}</button>
  `).join('');
  $('#sourceChips').innerHTML = sources.map(s => `
    <button class="chip ${state.selectedSources.has(s.id) ? 'active' : ''}" data-source="${escapeHtml(s.id)}">${escapeHtml(s.name)}</button>
  `).join('');

  document.querySelectorAll('[data-team]').forEach(btn => btn.addEventListener('click', () => {
    const id = btn.dataset.team;
    state.selectedTeams.has(id) ? state.selectedTeams.delete(id) : state.selectedTeams.add(id);
    saveStore(); renderAll();
  }));
  document.querySelectorAll('[data-source]').forEach(btn => btn.addEventListener('click', () => {
    const id = btn.dataset.source;
    state.selectedSources.has(id) ? state.selectedSources.delete(id) : state.selectedSources.add(id);
    saveStore(); renderAll();
  }));
}

function collectTeams(videos) {
  const map = new Map();
  videos.forEach(v => (v.teams || []).forEach(t => map.set(t.id, t)));
  return [...map.values()].sort((a,b) => a.name.localeCompare(b.name, 'fr'));
}
function collectSources(videos, statuses) {
  const map = new Map();
  videos.forEach(v => map.set(v.source_id, { id: v.source_id, name: v.source_name }));
  statuses.forEach(s => map.set(s.source_id, { id: s.source_id, name: s.source_name }));
  return [...map.values()].filter(Boolean).sort((a,b) => a.name.localeCompare(b.name, 'fr'));
}

function filteredVideos() {
  const q = state.search.trim().toLocaleLowerCase('fr');
  return (state.data?.videos || []).filter(v => {
    if (state.selectedTeams.size && !(v.teams || []).some(t => state.selectedTeams.has(t.id))) return false;
    if (state.selectedSources.size && !state.selectedSources.has(v.source_id)) return false;
    if (state.favoritesOnly && !state.selectedTeams.size) return false;
    if (state.favoritesOnly && !(v.teams || []).some(t => state.selectedTeams.has(t.id))) return false;
    if (state.unseenOnly && state.seen.has(v.id)) return false;
    const text = `${v.title} ${v.source_name} ${(v.teams || []).map(t => t.name).join(' ')}`.toLocaleLowerCase('fr');
    if (q && !text.includes(q)) return false;
    return true;
  });
}

function renderFeed() {
  const videos = filteredVideos();
  $('#empty').classList.toggle('hidden', videos.length !== 0);
  $('#feed').innerHTML = videos.map(v => {
    const isUnseen = !state.seen.has(v.id);
    return `
      <article class="card">
        <a class="thumb-wrap" href="${escapeHtml(v.url)}" target="_blank" rel="noopener noreferrer" data-open="${escapeHtml(v.id)}">
          <img class="thumb" loading="lazy" src="${escapeHtml(v.thumbnail)}" alt="" onerror="this.style.display='none'">
          ${isUnseen ? '<span class="unseen">NOUVEAU</span>' : ''}
        </a>
        <div class="card-body">
          <div class="teams">${(v.teams || []).map(t => `<span class="team-tag">${escapeHtml(t.name)}</span>`).join('')}</div>
          <h3 class="card-title">${escapeHtml(v.title)}</h3>
          <div class="meta"><span>${escapeHtml(v.source_name)}</span><span>${formatDate(v.published_at)}</span></div>
          <div class="card-actions">
            <a class="watch" href="${escapeHtml(v.url)}" target="_blank" rel="noopener noreferrer" data-open="${escapeHtml(v.id)}">▶ Voir sur YouTube</a>
            <button class="seen-btn" title="Marquer comme ${isUnseen ? 'vu' : 'non vu'}" data-seen="${escapeHtml(v.id)}">${isUnseen ? '✓' : '↺'}</button>
          </div>
        </div>
      </article>
    `;
  }).join('');

  document.querySelectorAll('[data-open]').forEach(el => el.addEventListener('click', () => {
    state.seen.add(el.dataset.open); saveStore();
  }));
  document.querySelectorAll('[data-seen]').forEach(btn => btn.addEventListener('click', (e) => {
    e.preventDefault();
    const id = btn.dataset.seen;
    state.seen.has(id) ? state.seen.delete(id) : state.seen.add(id);
    saveStore(); renderAll();
  }));
}

function renderAll() {
  renderStats();
  renderChips();
  $('#favoritesToggle').classList.toggle('active', state.favoritesOnly);
  $('#unseenToggle').classList.toggle('active', state.unseenOnly);
  renderFeed();
}

async function boot() {
  loadStore();
  const res = await fetch(`${DATA_URL}?t=${Date.now()}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Impossible de charger les données (${res.status})`);
  state.data = await res.json();
  // Preserve the user's local team selection even when the dataset changes.
  const knownTeams = new Set(collectTeams(state.data.videos || []).map(t => t.id));
  state.selectedTeams = new Set([...state.selectedTeams].filter(id => knownTeams.has(id)));
  $('#updatedAt').textContent = state.data.generated_at ? `Dernière collecte : ${formatDate(state.data.generated_at)}` : 'Pas encore de collecte';
  renderAll();
}

$('#search').addEventListener('input', e => { state.search = e.target.value; renderFeed(); });
$('#favoritesToggle').addEventListener('click', () => {
  state.favoritesOnly = !state.favoritesOnly;
  // "Mes équipes" active le filtre sur les équipes actuellement sélectionnées.
  if (state.favoritesOnly && !state.selectedTeams.size) {
    alert('Sélectionne au moins une équipe pour utiliser ce filtre.');
    state.favoritesOnly = false;
    return;
  }
  saveStore(); renderAll();
});
$('#unseenToggle').addEventListener('click', () => { state.unseenOnly = !state.unseenOnly; saveStore(); renderAll(); });
$('#themeBtn').addEventListener('click', () => { state.theme = state.theme === 'dark' ? 'light' : 'dark'; saveStore(); applyTheme(); });
$('#resetBtn').addEventListener('click', () => {
  localStorage.removeItem(STORE_KEY);
  state.selectedTeams.clear(); state.selectedSources.clear(); state.seen.clear(); state.favoritesOnly = false; state.unseenOnly = false;
  state.theme = 'light'; state.search = '';
  $('#search').value = '';
  applyTheme(); renderAll();
});

boot().catch(err => {
  console.error(err);
  $('#empty').classList.remove('hidden');
  $('#empty').querySelector('h3').textContent = 'Impossible de charger les données.';
  $('#empty').querySelector('p').textContent = `${err.message}. Vérifie que data/videos.json existe dans le dépôt.`;
});
