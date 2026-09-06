const DATA_URL = './data/videos.json';
const STORE_KEY = 'football-hub:v2';

const state = {
  data: null,
  selectedTeams: new Set(),
  selectedSources: new Set(),
  favoritesOnly: false,
  unseenOnly: false,
  search: '',
  seen: new Set(),
  theme: 'light',
  activeVideoId: null
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
  const themeBtn = $('#themeBtn');
  if (themeBtn) themeBtn.textContent = state.theme === 'dark' ? '☾' : '☼';
}

function formatDate(value) {
  if (!value) return 'Date inconnue';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return 'Date inconnue';
  const delta = Math.max(0, Date.now() - d.getTime());
  const minute = 60000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (delta < minute) return 'à l’instant';
  if (delta < hour) return `il y a ${Math.floor(delta / minute)} min`;
  if (delta < day) return `il y a ${Math.floor(delta / hour)} h`;
  if (delta < 7 * day) return `il y a ${Math.floor(delta / day)} j`;
  return new Intl.DateTimeFormat('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' }).format(d);
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  }[c]));
}

function videoIdFromUrl(url) {
  try {
    const u = new URL(url);
    return u.searchParams.get('v') || u.pathname.split('/').filter(Boolean).pop() || '';
  } catch (_) {
    return '';
  }
}

function ensureModal() {
  if ($('#videoModal')) return;
  document.body.insertAdjacentHTML('beforeend', `
    <div id="videoModal" class="video-modal hidden" aria-hidden="true">
      <div class="video-modal-backdrop" data-modal-close></div>
      <section class="video-modal-panel" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
        <div class="video-modal-header">
          <div>
            <div id="modalMeta" class="video-modal-meta"></div>
            <h2 id="modalTitle">Lecture</h2>
          </div>
          <button id="modalClose" class="video-modal-close" aria-label="Fermer">✕</button>
        </div>
        <div class="video-frame-wrap">
          <iframe id="videoPlayer" title="Lecteur YouTube" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe>
        </div>
        <div class="video-modal-footer">
          <div id="modalSources" class="video-source-list"></div>
          <a id="openYoutube" class="watch secondary" target="_blank" rel="noopener noreferrer">↗ Ouvrir sur YouTube</a>
        </div>
        <p class="embed-note">Si YouTube n'autorise pas la lecture intégrée pour cette vidéo, utilise le bouton « Ouvrir sur YouTube ».</p>
      </section>
    </div>
  `);

  $('#modalClose').addEventListener('click', closeModal);
  document.querySelectorAll('[data-modal-close]').forEach((el) => el.addEventListener('click', closeModal));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('#videoModal').classList.contains('hidden')) closeModal();
  });
}

function openModal(video, match) {
  ensureModal();
  const modal = $('#videoModal');
  const player = $('#videoPlayer');
  const id = video.id || videoIdFromUrl(video.url);
  if (!id) return;

  state.activeVideoId = id;
  state.seen.add(id);
  saveStore();

  const origin = encodeURIComponent(location.origin);
  player.src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?autoplay=1&playsinline=1&rel=0&modestbranding=1&origin=${origin}`;
  $('#modalTitle').textContent = match?.title || video.match_title || video.title || 'Résumé';
  $('#modalMeta').textContent = `${video.source_name || 'YouTube'} · ${formatDate(video.published_at)}`;
  $('#openYoutube').href = video.url || `https://www.youtube.com/watch?v=${encodeURIComponent(id)}`;

  const sources = match?.videos || [video];
  $('#modalSources').innerHTML = sources.map((source) => `
    <button class="source-choice ${source.id === id ? 'active' : ''}" data-video-id="${escapeHtml(source.id)}">
      <span>${escapeHtml(source.source_name || 'YouTube')}</span>
      <small>${formatDate(source.published_at)}</small>
    </button>
  `).join('');

  $('#modalSources').querySelectorAll('[data-video-id]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const next = sources.find((s) => s.id === btn.dataset.videoId);
      if (next) openModal(next, match);
    });
  });

  modal.classList.remove('hidden');
  modal.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');
}

function closeModal() {
  const modal = $('#videoModal');
  if (!modal) return;
  const player = $('#videoPlayer');
  if (player) player.src = '';
  modal.classList.add('hidden');
  modal.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('modal-open');
  state.activeVideoId = null;
}

function renderStats() {
  const videos = state.data?.videos || [];
  const matches = state.data?.matches || [];
  const unseen = videos.filter((v) => !state.seen.has(v.id)).length;
  const stats = $('#stats');
  if (!stats) return;
  stats.innerHTML = `
    <div class="stat"><div class="stat-value">${matches.length}</div><div class="stat-label">matchs conservés</div></div>
    <div class="stat"><div class="stat-value">${unseen}</div><div class="stat-label">nouveaux pour toi</div></div>
  `;
}

function collectTeams(videos) {
  const map = new Map();
  videos.forEach((v) => (v.teams || []).forEach((t) => {
    if (t?.id) map.set(t.id, t);
  }));
  return [...map.values()].sort((a, b) => a.name.localeCompare(b.name, 'fr'));
}

function collectSources(videos, statuses) {
  const map = new Map();
  videos.forEach((v) => {
    if (v.source_id) map.set(v.source_id, { id: v.source_id, name: v.source_name || v.source_id });
  });
  statuses.forEach((s) => {
    if (s.source_id) map.set(s.source_id, { id: s.source_id, name: s.source_name || s.source_id });
  });
  return [...map.values()].sort((a, b) => a.name.localeCompare(b.name, 'fr'));
}

function renderChips() {
  const d = state.data || { teams: [], videos: [], source_status: [] };
  const teams = Array.isArray(d.teams) && d.teams.length ? d.teams : collectTeams(d.videos || []);
  const sources = collectSources(d.videos || [], d.source_status || []);
  $('#teamChips').innerHTML = teams.map((t) => `
    <button class="chip ${state.selectedTeams.has(t.id) ? 'active' : ''}" data-team="${escapeHtml(t.id)}">${escapeHtml(t.name)}</button>
  `).join('');
  $('#sourceChips').innerHTML = sources.map((s) => `
    <button class="chip ${state.selectedSources.has(s.id) ? 'active' : ''}" data-source="${escapeHtml(s.id)}">${escapeHtml(s.name)}</button>
  `).join('');

  document.querySelectorAll('[data-team]').forEach((btn) => btn.addEventListener('click', () => {
    const id = btn.dataset.team;
    if (state.selectedTeams.has(id)) state.selectedTeams.delete(id); else state.selectedTeams.add(id);
    saveStore(); renderAll();
  }));
  document.querySelectorAll('[data-source]').forEach((btn) => btn.addEventListener('click', () => {
    const id = btn.dataset.source;
    if (state.selectedSources.has(id)) state.selectedSources.delete(id); else state.selectedSources.add(id);
    saveStore(); renderAll();
  }));
}

function filteredMatches() {
  const q = state.search.trim().toLocaleLowerCase('fr');
  const matches = state.data?.matches || buildLegacyMatches(state.data?.videos || []);
  return matches.filter((m) => {
    const teamIds = new Set(m.team_ids || []);
    const videos = m.videos || [];
    if (state.selectedTeams.size && ![...state.selectedTeams].some((id) => teamIds.has(id))) return false;
    if (state.selectedSources.size && !videos.some((v) => state.selectedSources.has(v.source_id))) return false;
    if (state.favoritesOnly && !state.selectedTeams.size) return false;
    if (state.favoritesOnly && ![...state.selectedTeams].some((id) => teamIds.has(id))) return false;
    if (state.unseenOnly && !videos.some((v) => !state.seen.has(v.id))) return false;
    const text = `${m.title || ''} ${(m.team_names || []).join(' ')} ${videos.map((v) => `${v.title} ${v.source_name}`).join(' ')}`.toLocaleLowerCase('fr');
    return !q || text.includes(q);
  });
}

function buildLegacyMatches(videos) {
  const groups = new Map();
  videos.forEach((v) => {
    const key = v.match_key || v.id;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(v);
  });
  return [...groups.entries()].map(([match_key, items]) => {
    items.sort((a, b) => (b.published_at || '').localeCompare(a.published_at || ''));
    const teamMap = new Map();
    items.forEach((v) => (v.teams || []).forEach((t) => teamMap.set(t.id, t.name)));
    return {
      match_key,
      team_ids: [...teamMap.keys()],
      team_names: [...teamMap.values()],
      title: items[0]?.match_title || items[0]?.title || 'Résumé',
      score: items.find((v) => v.score)?.score || null,
      published_at: items[0]?.published_at || null,
      videos: items
    };
  }).sort((a, b) => (b.published_at || '').localeCompare(a.published_at || ''));
}

function renderFeed() {
  const matches = filteredMatches();
  $('#empty').classList.toggle('hidden', matches.length !== 0);

  $('#feed').innerHTML = matches.map((m) => {
    const videos = [...(m.videos || [])].sort((a, b) => (b.published_at || '').localeCompare(a.published_at || ''));
    const featured = videos[0];
    const isUnseen = videos.some((v) => !state.seen.has(v.id));
    const title = m.title || featured?.match_title || featured?.title || 'Résumé';
    const teams = (m.team_names || []).map((name) => `<span class="team-tag">${escapeHtml(name)}</span>`).join('');
    const sources = videos.map((v) => `
      <button class="source-row" data-play-match="${escapeHtml(m.match_key)}" data-video-id="${escapeHtml(v.id)}">
        <span><strong>${escapeHtml(v.source_name || 'YouTube')}</strong></span>
        <span class="source-row-right">▶ ${formatDate(v.published_at)}</span>
      </button>
    `).join('');

    return `
      <article class="card match-card">
        <button class="thumb-wrap thumb-button" type="button" data-play-match="${escapeHtml(m.match_key)}" data-video-id="${escapeHtml(featured?.id || '')}" aria-label="Lire ${escapeHtml(title)}">
          <img class="thumb" loading="lazy" src="${escapeHtml(featured?.thumbnail || '')}" alt="">
          ${isUnseen ? '<span class="unseen">NOUVEAU</span>' : ''}
          <span class="play-overlay">▶</span>
        </button>
        <div class="card-body">
          <div class="teams">${teams || '<span class="team-tag">Football</span>'}</div>
          <h3 class="card-title">${escapeHtml(title)}</h3>
          ${m.score ? `<div class="match-score">Score : ${escapeHtml(m.score)}</div>` : ''}
          <div class="meta"><span>${videos.length} source${videos.length > 1 ? 's' : ''}</span><span>${formatDate(m.published_at)}</span></div>
          <div class="source-list">${sources}</div>
          <div class="card-actions">
            <button class="watch" type="button" data-play-match="${escapeHtml(m.match_key)}" data-video-id="${escapeHtml(featured?.id || '')}">▶ Lire le résumé</button>
            <button class="seen-btn" title="Marquer le match comme ${isUnseen ? 'vu' : 'non vu'}" data-seen-match="${escapeHtml(m.match_key)}">${isUnseen ? '✓' : '↺'}</button>
          </div>
        </div>
      </article>
    `;
  }).join('');

  document.querySelectorAll('[data-play-match]').forEach((el) => el.addEventListener('click', () => {
    const match = (state.data?.matches || []).find((m) => m.match_key === el.dataset.playMatch) || buildLegacyMatches(state.data?.videos || []).find((m) => m.match_key === el.dataset.playMatch);
    const video = match?.videos?.find((v) => v.id === el.dataset.videoId) || match?.videos?.[0];
    if (video) openModal(video, match);
  }));

  document.querySelectorAll('[data-seen-match]').forEach((btn) => btn.addEventListener('click', (e) => {
    e.preventDefault();
    const match = (state.data?.matches || []).find((m) => m.match_key === btn.dataset.seenMatch) || buildLegacyMatches(state.data?.videos || []).find((m) => m.match_key === btn.dataset.seenMatch);
    (match?.videos || []).forEach((v) => {
      if (state.seen.has(v.id)) state.seen.delete(v.id); else state.seen.add(v.id);
    });
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
  ensureModal();
  const res = await fetch(`${DATA_URL}?t=${Date.now()}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Impossible de charger les données (${res.status})`);
  state.data = await res.json();
  const knownTeams = new Set(collectTeams(state.data.videos || []).map((t) => t.id));
  state.selectedTeams = new Set([...state.selectedTeams].filter((id) => knownTeams.has(id)));
  $('#updatedAt').textContent = state.data.generated_at ? `Dernière collecte : ${formatDate(state.data.generated_at)}` : 'Pas encore de collecte';
  renderAll();
}

$('#search').addEventListener('input', (e) => { state.search = e.target.value; renderFeed(); });
$('#favoritesToggle').addEventListener('click', () => {
  state.favoritesOnly = !state.favoritesOnly;
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
  state.selectedTeams.clear(); state.selectedSources.clear(); state.seen.clear();
  state.favoritesOnly = false; state.unseenOnly = false; state.theme = 'light'; state.search = '';
  $('#search').value = '';
  applyTheme();
  renderAll();
});

boot().catch((err) => {
  console.error(err);
  $('#empty').classList.remove('hidden');
  $('#empty').querySelector('h3').textContent = 'Impossible de charger les données.';
  $('#empty').querySelector('p').textContent = `${err.message}. Vérifie que data/videos.json est bien publié avec le site.`;
});
