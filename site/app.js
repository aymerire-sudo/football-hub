const DATA_URL = './data/videos.json';
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

    if (Array.isArray(saved.selectedTeams)) {
      state.selectedTeams = new Set(saved.selectedTeams);
    }

    if (Array.isArray(saved.selectedSources)) {
      state.selectedSources = new Set(saved.selectedSources);
    }

    if (Array.isArray(saved.seen)) {
      state.seen = new Set(saved.seen);
    }

    state.favoritesOnly = Boolean(saved.favoritesOnly);
    state.unseenOnly = Boolean(saved.unseenOnly);

    state.theme =
      saved.theme ||
      (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  } catch (_) {
    // Ignore invalid localStorage data.
  }

  applyTheme();
}

function saveStore() {
  localStorage.setItem(
    STORE_KEY,
    JSON.stringify({
      selectedTeams: [...state.selectedTeams],
      selectedSources: [...state.selectedSources],
      seen: [...state.seen],
      favoritesOnly: state.favoritesOnly,
      unseenOnly: state.unseenOnly,
      theme: state.theme
    })
  );
}

function applyTheme() {
  document.documentElement.dataset.theme = state.theme;

  const themeBtn = $('#themeBtn');

  if (themeBtn) {
    themeBtn.textContent = state.theme === 'dark' ? '☾' : '☼';
  }
}

function formatDate(value) {
  if (!value) return 'Date inconnue';

  const d = new Date(value);

  if (Number.isNaN(d.getTime())) {
    return 'Date inconnue';
  }

  const now = Date.now();
  const delta = Math.max(0, now - d.getTime());

  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;

  if (delta < minute) {
    return 'à l’instant';
  }

  if (delta < hour) {
    return `il y a ${Math.floor(delta / minute)} min`;
  }

  if (delta < day) {
    return `il y a ${Math.floor(delta / hour)} h`;
  }

  if (delta < 7 * day) {
    return `il y a ${Math.floor(delta / day)} j`;
  }

  return new Intl.DateTimeFormat('fr-FR', {
    day: '2-digit',
    month: 'short',
    year: 'numeric'
  }).format(d);
}

function escapeHtml(s) {
  return String(s ?? '').replace(
    /[&<>"']/g,
    (c) =>
      ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
      })[c]
  );
}

function renderStats() {
  const d = state.data;
  const videos = d?.videos || [];

  const unseen = videos.filter((v) => !state.seen.has(v.id)).length;

  const stats = $('#stats');

  if (!stats) return;

  stats.innerHTML = `
    <div class="stat">
      <div class="stat-value">${videos.length}</div>
      <div class="stat-label">résumés conservés</div>
    </div>

    <div class="stat">
      <div class="stat-value">${unseen}</div>
      <div class="stat-label">nouveaux pour toi</div>
    </div>
  `;
}

function renderChips() {
  const d = state.data || {
    teams: [],
    videos: [],
    source_status: []
  };

  const teams = Array.isArray(d.teams)
    ? d.teams
    : collectTeams(d.videos || []);

  const sources = collectSources(
    d.videos || [],
    d.source_status || []
  );

  const teamChips = $('#teamChips');
  const sourceChips = $('#sourceChips');

  if (teamChips) {
    teamChips.innerHTML = teams
      .map(
        (t) => `
        <button
          class="chip ${state.selectedTeams.has(t.id) ? 'active' : ''}"
          data-team="${escapeHtml(t.id)}"
        >
          ${escapeHtml(t.name)}
        </button>
      `
      )
      .join('');
  }

  if (sourceChips) {
    sourceChips.innerHTML = sources
      .map(
        (s) => `
        <button
          class="chip ${state.selectedSources.has(s.id) ? 'active' : ''}"
          data-source="${escapeHtml(s.id)}"
        >
          ${escapeHtml(s.name)}
        </button>
      `
      )
      .join('');
  }

  document.querySelectorAll('[data-team]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.team;

      if (state.selectedTeams.has(id)) {
        state.selectedTeams.delete(id);
      } else {
        state.selectedTeams.add(id);
      }

      saveStore();
      renderAll();
    });
  });

  document.querySelectorAll('[data-source]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.source;

      if (state.selectedSources.has(id)) {
        state.selectedSources.delete(id);
      } else {
        state.selectedSources.add(id);
      }

      saveStore();
      renderAll();
    });
  });
}

function collectTeams(videos) {
  const map = new Map();

  videos.forEach((v) => {
    (v.teams || []).forEach((t) => {
      if (t?.id) {
        map.set(t.id, t);
      }
    });
  });

  return [...map.values()].sort((a, b) =>
    a.name.localeCompare(b.name, 'fr')
  );
}

function collectSources(videos, statuses) {
  const map = new Map();

  videos.forEach((v) => {
    if (v.source_id) {
      map.set(v.source_id, {
        id: v.source_id,
        name: v.source_name || v.source_id
      });
    }
  });

  statuses.forEach((s) => {
    if (s.source_id) {
      map.set(s.source_id, {
        id: s.source_id,
        name: s.source_name || s.source_id
      });
    }
  });

  return [...map.values()]
    .filter(Boolean)
    .sort((a, b) => a.name.localeCompare(b.name, 'fr'));
}

function filteredVideos() {
  const q = state.search.trim().toLocaleLowerCase('fr');

  return (state.data?.videos || []).filter((v) => {
    const videoTeams = v.teams || [];

    if (
      state.selectedTeams.size &&
      !videoTeams.some((t) => state.selectedTeams.has(t.id))
    ) {
      return false;
    }

    if (
      state.selectedSources.size &&
      !state.selectedSources.has(v.source_id)
    ) {
      return false;
    }

    if (
      state.favoritesOnly &&
      !state.selectedTeams.size
    ) {
      return false;
    }

    if (
      state.favoritesOnly &&
      !videoTeams.some((t) => state.selectedTeams.has(t.id))
    ) {
      return false;
    }

    if (
      state.unseenOnly &&
      state.seen.has(v.id)
    ) {
      return false;
    }

    const text = `
      ${v.title || ''}
      ${v.source_name || ''}
      ${videoTeams.map((t) => t.name || '').join(' ')}
    `.toLocaleLowerCase('fr');

    if (q && !text.includes(q)) {
      return false;
    }

    return true;
  });
}

function renderFeed() {
  const videos = filteredVideos();

  const empty = $('#empty');
  const feed = $('#feed');

  if (!empty || !feed) return;

  empty.classList.toggle('hidden', videos.length !== 0);

  feed.innerHTML = videos
    .map((v) => {
      const isUnseen = !state.seen.has(v.id);

      return `
        <article class="card">
          <a
            class="thumb-wrap"
            href="${escapeHtml(v.url)}"
            target="_blank"
            rel="noopener noreferrer"
            data-open="${escapeHtml(v.id)}"
          >
            <img
              class="thumb"
              loading="lazy"
              src="${escapeHtml(v.thumbnail || '')}"
              alt=""
              onerror="this.style.display='none'"
            >

            ${
              isUnseen
                ? '<span class="unseen">NOUVEAU</span>'
                : ''
            }
          </a>

          <div class="card-body">
            <div class="teams">
              ${(v.teams || [])
                .map(
                  (t) => `
                    <span class="team-tag">
                      ${escapeHtml(t.name)}
                    </span>
                  `
                )
                .join('')}
            </div>

            <h3 class="card-title">
              ${escapeHtml(v.title)}
            </h3>

            <div class="meta">
              <span>${escapeHtml(v.source_name)}</span>
              <span>${formatDate(v.published_at)}</span>
            </div>

            <div class="card-actions">
              <a
                class="watch"
                href="${escapeHtml(v.url)}"
                target="_blank"
                rel="noopener noreferrer"
                data-open="${escapeHtml(v.id)}"
              >
                ▶ Voir sur YouTube
              </a>

              <button
                class="seen-btn"
                title="Marquer comme ${
                  isUnseen ? 'vu' : 'non vu'
                }"
                data-seen="${escapeHtml(v.id)}"
              >
                ${isUnseen ? '✓' : '↺'}
              </button>
            </div>
          </div>
        </article>
      `;
    })
    .join('');

  document.querySelectorAll('[data-open]').forEach((el) => {
    el.addEventListener('click', () => {
      const id = el.dataset.open;

      if (!id) return;

      state.seen.add(id);
      saveStore();
    });
  });

  document.querySelectorAll('[data-seen]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();

      const id = btn.dataset.seen;

      if (!id) return;

      if (state.seen.has(id)) {
        state.seen.delete(id);
      } else {
        state.seen.add(id);
      }

      saveStore();
      renderAll();
    });
  });
}

function renderAll() {
  renderStats();
  renderChips();

  const favoritesToggle = $('#favoritesToggle');
  const unseenToggle = $('#unseenToggle');

  if (favoritesToggle) {
    favoritesToggle.classList.toggle(
      'active',
      state.favoritesOnly
    );
  }

  if (unseenToggle) {
    unseenToggle.classList.toggle(
      'active',
      state.unseenOnly
    );
  }

  renderFeed();
}

async function boot() {
  loadStore();

  const res = await fetch(
    `${DATA_URL}?t=${Date.now()}`,
    {
      cache: 'no-store'
    }
  );

  if (!res.ok) {
    throw new Error(
      `Impossible de charger les données (${res.status})`
    );
  }

  const data = await res.json();

  if (!data || typeof data !== 'object') {
    throw new Error(
      'Le fichier data/videos.json est invalide'
    );
  }

  state.data = data;

  const knownTeams = new Set(
    collectTeams(state.data.videos || []).map(
      (t) => t.id
    )
  );

  state.selectedTeams = new Set(
    [...state.selectedTeams].filter((id) =>
      knownTeams.has(id)
    )
  );

  const updatedAt = $('#updatedAt');

  if (updatedAt) {
    updatedAt.textContent = state.data.generated_at
      ? `Dernière collecte : ${formatDate(
          state.data.generated_at
        )}`
      : 'Pas encore de collecte';
  }

  renderAll();
}

const search = $('#search');

if (search) {
  search.addEventListener('input', (e) => {
    state.search = e.target.value;
    renderFeed();
  });
}

const favoritesToggle = $('#favoritesToggle');

if (favoritesToggle) {
  favoritesToggle.addEventListener('click', () => {
    state.favoritesOnly = !state.favoritesOnly;

    if (
      state.favoritesOnly &&
      !state.selectedTeams.size
    ) {
      alert(
        'Sélectionne au moins une équipe pour utiliser ce filtre.'
      );

      state.favoritesOnly = false;
      return;
    }

    saveStore();
    renderAll();
  });
}

const unseenToggle = $('#unseenToggle');

if (unseenToggle) {
  unseenToggle.addEventListener('click', () => {
    state.unseenOnly = !state.unseenOnly;

    saveStore();
    renderAll();
  });
}

const themeBtn = $('#themeBtn');

if (themeBtn) {
  themeBtn.addEventListener('click', () => {
    state.theme =
      state.theme === 'dark' ? 'light' : 'dark';

    saveStore();
    applyTheme();
  });
}

const resetBtn = $('#resetBtn');

if (resetBtn) {
  resetBtn.addEventListener('click', () => {
    localStorage.removeItem(STORE_KEY);

    state.selectedTeams.clear();
    state.selectedSources.clear();
    state.seen.clear();

    state.favoritesOnly = false;
    state.unseenOnly = false;
    state.theme = 'light';
    state.search = '';

    if (search) {
      search.value = '';
    }

    applyTheme();

    if (state.data) {
      renderAll();
    }
  });
}

boot().catch((err) => {
  console.error(err);

  const empty = $('#empty');

  if (!empty) return;

  empty.classList.remove('hidden');

  const title = empty.querySelector('h3');
  const description = empty.querySelector('p');

  if (title) {
    title.textContent =
      'Impossible de charger les données.';
  }

  if (description) {
    description.textContent =
      `${err.message}. Vérifie que data/videos.json est bien publié avec le site.`;
  }
});
