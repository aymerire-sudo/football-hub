const DATA_URL = './data/videos.json';
const STORE_KEY = 'football-hub:v4';

const state = {
  data: null,
  selectedTeams: new Set(),
  selectedSources: new Set(),
  favoritesOnly: false,
  unseenOnly: false,
  search: '',
  seen: new Set(),
  theme: 'light',
  activeVideoId: null,
  activeMatch: null,
  playbackTimer: null
};

const $ = (selector) =>
  document.querySelector(selector);

/* ============================================================
   STOCKAGE / THEME
   ============================================================ */

function loadStore() {
  try {
    const saved = JSON.parse(
      localStorage.getItem(STORE_KEY) || '{}'
    );

    if (Array.isArray(saved.selectedTeams)) {
      state.selectedTeams = new Set(
        saved.selectedTeams
      );
    }

    if (Array.isArray(saved.selectedSources)) {
      state.selectedSources = new Set(
        saved.selectedSources
      );
    }

    if (Array.isArray(saved.seen)) {
      state.seen = new Set(saved.seen);
    }

    state.favoritesOnly = Boolean(
      saved.favoritesOnly
    );

    state.unseenOnly = Boolean(
      saved.unseenOnly
    );

    state.theme =
      saved.theme ||
      (
        matchMedia(
          '(prefers-color-scheme: dark)'
        ).matches
          ? 'dark'
          : 'light'
      );
  } catch (_) {
    // Ignore invalid localStorage.
  }

  applyTheme();
}

function saveStore() {
  try {
    localStorage.setItem(
      STORE_KEY,
      JSON.stringify({
        selectedTeams: [
          ...state.selectedTeams
        ],
        selectedSources: [
          ...state.selectedSources
        ],
        seen: [
          ...state.seen
        ],
        favoritesOnly:
          state.favoritesOnly,
        unseenOnly:
          state.unseenOnly,
        theme: state.theme
      })
    );
  } catch (_) {
    // Ignore localStorage errors.
  }
}

function applyTheme() {
  document.documentElement.dataset.theme =
    state.theme;

  const button = $('#themeBtn');

  if (button) {
    button.textContent =
      state.theme === 'dark'
        ? '☾'
        : '☼';
  }
}

/* ============================================================
   DATES / TEXTE
   ============================================================ */

function parseDate(value) {
  if (!value) return null;

  const date = new Date(value);

  return Number.isNaN(
    date.getTime()
  )
    ? null
    : date;
}

function formatDate(value) {
  const date = parseDate(value);

  if (!date) {
    return 'Date inconnue';
  }

  const delta = Math.max(
    0,
    Date.now() -
      date.getTime()
  );

  const minute = 60_000;
  const hour =
    60 * minute;
  const day =
    24 * hour;

  if (delta < minute) {
    return 'à l’instant';
  }

  if (delta < hour) {
    return (
      `il y a ` +
      `${Math.floor(
        delta / minute
      )} min`
    );
  }

  if (delta < day) {
    return (
      `il y a ` +
      `${Math.floor(
        delta / hour
      )} h`
    );
  }

  if (delta < 7 * day) {
    return (
      `il y a ` +
      `${Math.floor(
        delta / day
      )} j`
    );
  }

  return new Intl.DateTimeFormat(
    'fr-FR',
    {
      day: '2-digit',
      month: 'short',
      year: 'numeric'
    }
  ).format(date);
}

function formatMatchDate(value) {
  const date = parseDate(value);

  if (!date) {
    return '';
  }

  return new Intl.DateTimeFormat(
    'fr-FR',
    {
      day: '2-digit',
      month: 'long',
      year: 'numeric'
    }
  ).format(date);
}

function escapeHtml(value) {
  return String(
    value ?? ''
  ).replace(
    /[&<>"']/g,
    (char) =>
      ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
      })[char]
  );
}

/* ============================================================
   YOUTUBE
   ============================================================ */

function videoIdFromUrl(url) {
  if (!url) return '';

  try {
    const parsed = new URL(url);

    // https://www.youtube.com/watch?v=XXXXXXXXXXX
    const fromQuery =
      parsed.searchParams.get('v');

    if (fromQuery) {
      return fromQuery;
    }

    // https://youtu.be/XXXXXXXXXXX
    if (
      parsed.hostname.includes('youtu.be')
    ) {
      return (
        parsed.pathname
          .split('/')
          .filter(Boolean)[0] || ''
      );
    }

    // https://www.youtube.com/shorts/XXXXXXXXXXX
    const parts =
      parsed.pathname
        .split('/')
        .filter(Boolean);

    const specialIndex =
      parts.findIndex(
        (part) =>
          part === 'shorts' ||
          part === 'embed' ||
          part === 'live'
      );

    if (
      specialIndex >= 0 &&
      parts[specialIndex + 1]
    ) {
      return parts[
        specialIndex + 1
      ];
    }

    return parts.at(-1) || '';
  } catch (_) {
    return '';
  }
}

function getYoutubeUrl(
  video,
  videoId
) {
  return (
    video?.url ||
    `https://www.youtube.com/watch?v=${encodeURIComponent(
      videoId
    )}`
  );
}

function clearPlaybackTimer() {
  if (state.playbackTimer) {
    clearTimeout(
      state.playbackTimer
    );

    state.playbackTimer = null;
  }
}

function showPlayerFallback(
  message
) {
  const fallback =
    $('#playerFallback');

  const fallbackText =
    $('#playerFallbackText');

  if (!fallback) return;

  if (fallbackText) {
    fallbackText.textContent =
      message;
  }

  fallback.classList.remove(
    'hidden'
  );
}

function hidePlayerFallback() {
  const fallback =
    $('#playerFallback');

  if (fallback) {
    fallback.classList.add(
      'hidden'
    );
  }
}

function schedulePlaybackCheck() {
  clearPlaybackTimer();

  /*
   * On ne peut pas lire le contenu visuel d'un iframe YouTube
   * car il est sur un autre domaine.
   *
   * On utilise donc un délai de sécurité :
   * si la vidéo ne se lance pas, on affiche le fallback.
   */
  state.playbackTimer =
    setTimeout(() => {
      if (
        !state.activeVideoId
      ) {
        return;
      }

      showPlayerFallback(
        'La lecture intégrée ne démarre pas. La vidéo peut être bloquée dans ton pays, interdire la lecture intégrée ou être momentanément indisponible.'
      );
    }, 8000);
}

function buildYoutubeEmbedUrl(
  videoId
) {
  return (
    'https://www.youtube-nocookie.com/embed/' +
    `${encodeURIComponent(
      videoId
    )}` +
    '?autoplay=1' +
    '&playsinline=1' +
    '&rel=0' +
    '&modestbranding=1' +
    '&enablejsapi=1'
  );
}

/* ============================================================
   MODAL
   ============================================================ */

function ensureModal() {
  if ($('#videoModal')) {
    return;
  }

  document.body.insertAdjacentHTML(
    'beforeend',
    `
      <div
        id="videoModal"
        class="video-modal hidden"
        aria-hidden="true"
      >
        <div
          class="video-modal-backdrop"
          data-modal-close
        ></div>

        <section
          class="video-modal-panel"
          role="dialog"
          aria-modal="true"
          aria-labelledby="modalTitle"
        >

          <div class="video-modal-header">
            <div>
              <div
                id="modalMeta"
                class="video-modal-meta"
              ></div>

              <h2 id="modalTitle">
                Lecture
              </h2>
            </div>

            <button
              id="modalClose"
              class="video-modal-close"
              type="button"
              aria-label="Fermer"
            >
              ✕
            </button>
          </div>

          <div class="video-frame-wrap">

            <iframe
              id="videoPlayer"
              title="Lecteur YouTube"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
              allowfullscreen
              referrerpolicy="strict-origin-when-cross-origin"
            ></iframe>

            <div
              id="playerFallback"
              class="player-fallback hidden"
            >
              <div class="player-fallback-icon">
                ▶
              </div>

              <strong>
                Lecture intégrée indisponible
              </strong>

              <p
                id="playerFallbackText"
              >
                La vidéo ne peut pas être
                lue directement dans Football Hub.
              </p>

              <div
                class="player-fallback-actions"
              >

                <a
                  id="fallbackYoutube"
                  class="watch"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  ↗ Ouvrir sur YouTube
                </a>

                <button
                  id="fallbackAnother"
                  class="watch secondary"
                  type="button"
                >
                  Choisir une autre source
                </button>

              </div>
            </div>
          </div>

          <div class="video-modal-footer">

            <div
              id="modalSources"
              class="video-source-list"
            ></div>

            <a
              id="openYoutube"
              class="watch secondary"
              target="_blank"
              rel="noopener noreferrer"
            >
              ↗ Ouvrir sur YouTube
            </a>

          </div>

          <p class="embed-note">
            Certaines vidéos YouTube peuvent être
            limitées selon le pays ou ne pas autoriser
            la lecture intégrée.
          </p>

        </section>
      </div>
    `
  );

  $('#modalClose').addEventListener(
    'click',
    closeModal
  );

  document
    .querySelectorAll(
      '[data-modal-close]'
    )
    .forEach((element) => {
      element.addEventListener(
        'click',
        closeModal
      );
    });

  document.addEventListener(
    'keydown',
    (event) => {
      const modal =
        $('#videoModal');

      if (
        event.key === 'Escape' &&
        modal &&
        !modal.classList.contains(
          'hidden'
        )
      ) {
        closeModal();
      }
    }
  );

  $('#fallbackAnother')
    .addEventListener(
      'click',
      playAnotherSource
    );
}

function updateYoutubeLinks(
  video,
  videoId
) {
  const url =
    getYoutubeUrl(
      video,
      videoId
    );

  const openYoutube =
    $('#openYoutube');

  const fallbackYoutube =
    $('#fallbackYoutube');

  if (openYoutube) {
    openYoutube.href = url;
  }

  if (fallbackYoutube) {
    fallbackYoutube.href = url;
  }
}

function renderModalSources(
  sources,
  activeId
) {
  const container =
    $('#modalSources');

  if (!container) {
    return;
  }

  container.innerHTML =
    sources
      .map(
        (source) => {
          const sourceId =
            source.id ||
            videoIdFromUrl(
              source.url
            );

          return `
            <button
              class="source-choice ${
                sourceId === activeId
                  ? 'active'
                  : ''
              }"
              type="button"
              data-source-video-id="${escapeHtml(
                sourceId
              )}"
            >

              <span>
                ${escapeHtml(
                  source.source_name ||
                    'YouTube'
                )}
              </span>

              <small>
                ${formatDate(
                  source.published_at
                )}
              </small>

            </button>
          `;
        }
      )
      .join('');

  container
    .querySelectorAll(
      '[data-source-video-id]'
    )
    .forEach((button) => {
      button.addEventListener(
        'click',
        () => {
          const next =
            sources.find(
              (source) => {
                const sourceId =
                  source.id ||
                  videoIdFromUrl(
                    source.url
                  );

                return (
                  sourceId ===
                  button.dataset
                    .sourceVideoId
                );
              }
            );

          if (next) {
            openModal(
              next,
              state.activeMatch
            );
          }
        }
      );
    });
}

function openModal(
  video,
  match
) {
  ensureModal();

  const modal =
    $('#videoModal');

  const player =
    $('#videoPlayer');

  const id =
    video?.id ||
    videoIdFromUrl(
      video?.url
    );

  if (
    !modal ||
    !player ||
    !id
  ) {
    return;
  }

  clearPlaybackTimer();

  state.activeVideoId =
    id;

  state.activeMatch =
    match || null;

  state.seen.add(id);

  saveStore();

  const title =
    match?.title ||
    video.match_title ||
    video.title ||
    'Résumé';

  const dateText =
    match?.match_date
      ? `Match du ${formatMatchDate(
          match.match_date
        )}`
      : formatDate(
          video.published_at ||
            video.match_date
        );

  $('#modalTitle').textContent =
    title;

  $('#modalMeta').textContent =
    `${video.source_name || 'YouTube'} · ${dateText}`;

  updateYoutubeLinks(
    video,
    id
  );

  const sources =
    match?.videos?.length
      ? match.videos
      : [video];

  renderModalSources(
    sources,
    id
  );

  hidePlayerFallback();

  /*
   * On détruit l'ancienne source avant d'en charger
   * une nouvelle afin d'éviter de laisser une ancienne
   * vidéo jouer en arrière-plan.
   */
  player.src = '';

  /*
   * Petit délai pour laisser au navigateur le temps
   * de nettoyer l'ancien iframe.
   */
  setTimeout(() => {
    if (
      state.activeVideoId !== id
    ) {
      return;
    }

    player.src =
      buildYoutubeEmbedUrl(
        id
      );

    schedulePlaybackCheck();
  }, 50);

  modal.classList.remove(
    'hidden'
  );

  modal.setAttribute(
    'aria-hidden',
    'false'
  );

  document.body.classList.add(
    'modal-open'
  );
}

function playAnotherSource() {
  const match =
    state.activeMatch;

  const activeId =
    state.activeVideoId;

  const sources =
    match?.videos || [];

  if (
    sources.length <= 1
  ) {
    showPlayerFallback(
      'Aucune autre source officielle n’est disponible pour ce match.'
    );

    return;
  }

  const activeIndex =
    sources.findIndex(
      (video) => {
        const id =
          video.id ||
          videoIdFromUrl(
            video.url
          );

        return id === activeId;
      }
    );

  const nextIndex =
    activeIndex >= 0
      ? (
          activeIndex + 1
        ) %
        sources.length
      : 0;

  const next =
    sources[nextIndex];

  if (next) {
    openModal(
      next,
      match
    );
  }
}

function closeModal() {
  const modal =
    $('#videoModal');

  if (!modal) {
    return;
  }

  clearPlaybackTimer();

  const player =
    $('#videoPlayer');

  if (player) {
    player.src = '';
  }

  hidePlayerFallback();

  modal.classList.add(
    'hidden'
  );

  modal.setAttribute(
    'aria-hidden',
    'true'
  );

  document.body.classList.remove(
    'modal-open'
  );

  state.activeVideoId =
    null;

  state.activeMatch =
    null;
}

/* ============================================================
   DONNEES / FILTRES
   ============================================================ */

function renderStats() {
  const videos =
    state.data?.videos || [];

  const matches =
    state.data?.matches ||
    buildLegacyMatches(
      videos
    );

  const unseen =
    videos.filter(
      (video) =>
        !state.seen.has(
          video.id
        )
    ).length;

  const stats =
    $('#stats');

  if (!stats) {
    return;
  }

  stats.innerHTML = `
    <div class="stat">

      <div class="stat-value">
        ${matches.length}
      </div>

      <div class="stat-label">
        matchs conservés
      </div>

    </div>

    <div class="stat">

      <div class="stat-value">
        ${unseen}
      </div>

      <div class="stat-label">
        nouveaux pour toi
      </div>

    </div>
  `;
}

function collectTeams(
  videos
) {
  const map =
    new Map();

  videos.forEach(
    (video) => {
      (
        video.teams ||
        []
      ).forEach(
        (team) => {
          if (team?.id) {
            map.set(
              team.id,
              team
            );
          }
        }
      );
    }
  );

  return [
    ...map.values()
  ].sort(
    (a, b) =>
      a.name.localeCompare(
        b.name,
        'fr'
      )
  );
}

function collectSources(
  videos,
  statuses
) {
  const map =
    new Map();

  videos.forEach(
    (video) => {
      if (
        video.source_id
      ) {
        map.set(
          video.source_id,
          {
            id:
              video.source_id,
            name:
              video.source_name ||
              video.source_id
          }
        );
      }
    }
  );

  statuses.forEach(
    (status) => {
      if (
        status.source_id
      ) {
        map.set(
          status.source_id,
          {
            id:
              status.source_id,
            name:
              status.source_name ||
              status.source_id
          }
        );
      }
    }
  );

  return [
    ...map.values()
  ].sort(
    (a, b) =>
      a.name.localeCompare(
        b.name,
        'fr'
      )
  );
}

function renderChips() {
  const data =
    state.data || {
      teams: [],
      videos: [],
      source_status: []
    };

  const teams =
    Array.isArray(
      data.teams
    ) &&
    data.teams.length
      ? data.teams
      : collectTeams(
          data.videos || []
        );

  const sources =
    collectSources(
      data.videos || [],
      data.source_status || []
    );

  $('#teamChips').innerHTML =
    teams
      .map(
        (team) => `
          <button
            class="chip ${
              state.selectedTeams.has(
                team.id
              )
                ? 'active'
                : ''
            }"
            type="button"
            data-team="${escapeHtml(
              team.id
            )}"
          >
            ${escapeHtml(
              team.name
            )}
          </button>
        `
      )
      .join('');

  $('#sourceChips').innerHTML =
    sources
      .map(
        (source) => `
          <button
            class="chip ${
              state.selectedSources.has(
                source.id
              )
                ? 'active'
                : ''
            }"
            type="button"
            data-source="${escapeHtml(
              source.id
            )}"
          >
            ${escapeHtml(
              source.name
            )}
          </button>
        `
      )
      .join('');

  document
    .querySelectorAll(
      '[data-team]'
    )
    .forEach((button) => {
      button.addEventListener(
        'click',
        () => {
          const id =
            button.dataset
              .team;

          if (
            state.selectedTeams.has(
              id
            )
          ) {
            state.selectedTeams.delete(
              id
            );
          } else {
            state.selectedTeams.add(
              id
            );
          }

          saveStore();
          renderAll();
        }
      );
    });

  document
    .querySelectorAll(
      '[data-source]'
    )
    .forEach((button) => {
      button.addEventListener(
        'click',
        () => {
          const id =
            button.dataset
              .source;

          if (
            state.selectedSources.has(
              id
            )
          ) {
            state.selectedSources.delete(
              id
            );
          } else {
            state.selectedSources.add(
              id
            );
          }

          saveStore();
          renderAll();
        }
      );
    });
}

function buildLegacyMatches(
  videos
) {
  const groups =
    new Map();

  videos.forEach(
    (video) => {
      const key =
        video.match_key ||
        video.id;

      if (
        !groups.has(key)
      ) {
        groups.set(
          key,
          []
        );
      }

      groups
        .get(key)
        .push(video);
    }
  );

  return [
    ...groups.entries()
  ]
    .map(
      ([matchKey, items]) => {
        items.sort(
          (a, b) =>
            (
              b.published_at ||
              ''
            ).localeCompare(
              a.published_at ||
                ''
            )
        );

        const teamMap =
          new Map();

        items.forEach(
          (video) => {
            (
              video.teams ||
              []
            ).forEach(
              (team) => {
                if (
                  team?.id
                ) {
                  teamMap.set(
                    team.id,
                    team.name
                  );
                }
              }
            );
          }
        );

        return {
          match_key:
            matchKey,

          team_ids: [
            ...teamMap.keys()
          ],

          team_names: [
            ...teamMap.values()
          ],

          title:
            items[0]
              ?.match_title ||
            items[0]
              ?.title ||
            'Résumé',

          score:
            items.find(
              (video) =>
                video.score
            )?.score ||
            null,

          match_date:
            items[0]
              ?.match_date ||
            items[0]
              ?.published_at ||
            null,

          published_at:
            items[0]
              ?.published_at ||
            null,

          sources_count:
            new Set(
              items.map(
                (item) =>
                  item.source_id
              )
            ).size,

          videos:
            items
        };
      }
    )
    .sort(
      (a, b) =>
        (
          b.match_date ||
          ''
        ).localeCompare(
          a.match_date ||
            ''
        )
    );
}

function getMatches() {
  return state.data?.matches?.length
    ? state.data.matches
    : buildLegacyMatches(
        state.data?.videos || []
      );
}

function filteredMatches() {
  const query =
    state.search
      .trim()
      .toLocaleLowerCase(
        'fr'
      );

  return getMatches().filter(
    (match) => {
      const teamIds =
        new Set(
          match.team_ids ||
            []
        );

      const videos =
        match.videos ||
        [];

      if (
        state.selectedTeams
          .size &&
        ![
          ...state.selectedTeams
        ].some((id) =>
          teamIds.has(id)
        )
      ) {
        return false;
      }

      if (
        state.selectedSources
          .size &&
        !videos.some(
          (video) =>
            state.selectedSources.has(
              video.source_id
            )
        )
      ) {
        return false;
      }

      if (
        state.favoritesOnly &&
        !state.selectedTeams
          .size
      ) {
        return false;
      }

      if (
        state.favoritesOnly &&
        ![
          ...state.selectedTeams
        ].some((id) =>
          teamIds.has(id)
        )
      ) {
        return false;
      }

      if (
        state.unseenOnly &&
        !videos.some(
          (video) =>
            !state.seen.has(
              video.id
            )
        )
      ) {
        return false;
      }

      const searchable = [
        match.title,
        match.competition,

        ...(match.team_names ||
          []),

        ...(match.home_team
          ? [
              match.home_team
                .name
            ]
          : []),

        ...(match.away_team
          ? [
              match.away_team
                .name
            ]
          : []),

        ...videos.flatMap(
          (video) => [
            video.title,
            video.source_name
          ]
        )
      ]
        .filter(Boolean)
        .join(' ')
        .toLocaleLowerCase(
          'fr'
        );

      return (
        !query ||
        searchable.includes(
          query
        )
      );
    }
  );
}

/* ============================================================
   AFFICHAGE
   ============================================================ */

function renderFeed() {
  const matches =
    filteredMatches();

  const empty =
    $('#empty');

  const feed =
    $('#feed');

  empty.classList.toggle(
    'hidden',
    matches.length !== 0
  );

  if (!matches.length) {
    feed.innerHTML = '';
    return;
  }

  feed.innerHTML =
    matches
      .map((match) => {
        const videos = [
          ...(match.videos ||
            [])
        ].sort(
          (a, b) =>
            (
              b.published_at ||
              ''
            ).localeCompare(
              a.published_at ||
                ''
            )
        );

        const featured =
          videos[0];

        const isUnseen =
          videos.some(
            (video) =>
              !state.seen.has(
                video.id
              )
          );

        const title =
          match.title ||
          featured?.match_title ||
          featured?.title ||
          'Résumé';

        const teamTags =
          (
            match.team_names ||
            []
          )
            .map(
              (name) =>
                `<span class="team-tag">${escapeHtml(
                  name
                )}</span>`
            )
            .join('');

        const competition =
          match.competition
            ? `<span>${escapeHtml(
                match.competition
              )}</span>`
            : '';

        const sources =
          videos
            .map(
              (video) => `
                <button
                  class="source-row"
                  type="button"
                  data-play-match="${escapeHtml(
                    match.match_key
                  )}"
                  data-video-id="${escapeHtml(
                    video.id
                  )}"
                >

                  <span>
                    <strong>
                      ${escapeHtml(
                        video.source_name ||
                          'YouTube'
                      )}
                    </strong>
                  </span>

                  <span
                    class="source-row-right"
                  >
                    ▶ ${formatDate(
                      video.published_at ||
                        video.match_date
                    )}
                  </span>

                </button>
              `
            )
            .join('');

        return `
          <article
            class="card match-card"
          >

            <button
              class="thumb-wrap thumb-button"
              type="button"
              data-play-match="${escapeHtml(
                match.match_key
              )}"
              data-video-id="${escapeHtml(
                featured?.id || ''
              )}"
              aria-label="Lire ${escapeHtml(
                title
              )}"
            >

              <img
                class="thumb"
                loading="lazy"
                src="${escapeHtml(
                  featured?.thumbnail ||
                    ''
                )}"
                alt=""
                onerror="this.style.display='none'"
              >

              ${
                isUnseen
                  ? '<span class="unseen">NOUVEAU</span>'
                  : ''
              }

              <span class="play-overlay">
                ▶
              </span>

            </button>

            <div class="card-body">

              <div class="teams">
                ${
                  teamTags ||
                  '<span class="team-tag">Football</span>'
                }
              </div>

              <h3 class="card-title">
                ${escapeHtml(
                  title
                )}
              </h3>

              ${
                match.score
                  ? `
                    <div class="match-score">
                      Score :
                      ${escapeHtml(
                        match.score
                      )}
                    </div>
                  `
                  : ''
              }

              <div class="meta">

                <span>
                  ${
                    videos.length
                  }
                  source${
                    videos.length >
                    1
                      ? 's'
                      : ''
                  }
                </span>

                <span>
                  ${
                    escapeHtml(
                      formatMatchDate(
                        match.match_date
                      ) ||
                        formatDate(
                          match.published_at
                        )
                    )
                  }
                </span>

              </div>

              ${
                competition
                  ? `
                    <div class="competition">
                      ${competition}
                    </div>
                  `
                  : ''
              }

              <div class="source-list">
                ${sources}
              </div>

              <div class="card-actions">

                <button
                  class="watch"
                  type="button"
                  data-play-match="${escapeHtml(
                    match.match_key
                  )}"
                  data-video-id="${escapeHtml(
                    featured?.id ||
                      ''
                  )}"
                >
                  ▶ Lire le résumé
                </button>

                <button
                  class="seen-btn"
                  type="button"
                  title="Marquer le match comme ${
                    isUnseen
                      ? 'vu'
                      : 'non vu'
                  }"
                  data-seen-match="${escapeHtml(
                    match.match_key
                  )}"
                >
                  ${
                    isUnseen
                      ? '✓'
                      : '↺'
                  }
                </button>

              </div>

            </div>
          </article>
        `;
      })
      .join('');

  document
    .querySelectorAll(
      '[data-play-match]'
    )
    .forEach((element) => {
      element.addEventListener(
        'click',
        () => {
          const match =
            getMatches().find(
              (item) =>
                item.match_key ===
                element.dataset
                  .playMatch
            );

          const video =
            match?.videos?.find(
              (item) =>
                item.id ===
                element.dataset
                  .videoId
            ) ||
            match?.videos?.[0];

          if (video) {
            openModal(
              video,
              match
            );
          }
        }
      );
    });

  document
    .querySelectorAll(
      '[data-seen-match]'
    )
    .forEach((button) => {
      button.addEventListener(
        'click',
        (event) => {
          event.preventDefault();
          event.stopPropagation();

          const match =
            getMatches().find(
              (item) =>
                item.match_key ===
                button.dataset
                  .seenMatch
            );

          const videosForMatch =
            match?.videos || [];

          const allSeen =
            videosForMatch.length > 0 &&
            videosForMatch.every(
              (video) =>
                state.seen.has(
                  video.id
                )
            );

          videosForMatch.forEach(
            (video) => {
              if (allSeen) {
                state.seen.delete(
                  video.id
                );
              } else {
                state.seen.add(
                  video.id
                );
              }
            }
          );

          saveStore();
          renderAll();
        }
      );
    });
}

function renderAll() {
  renderStats();
  renderChips();

  $('#favoritesToggle')
    ?.classList.toggle(
      'active',
      state.favoritesOnly
    );

  $('#unseenToggle')
    ?.classList.toggle(
      'active',
      state.unseenOnly
    );

  renderFeed();
}

/* ============================================================
   INITIALISATION
   ============================================================ */

async function boot() {
  loadStore();
  ensureModal();

  const response =
    await fetch(
      `${DATA_URL}?t=${Date.now()}`,
      {
        cache: 'no-store'
      }
    );

  if (!response.ok) {
    throw new Error(
      `Impossible de charger les données (${response.status})`
    );
  }

  state.data =
    await response.json();

  const availableTeams =
    new Set(
      (
        state.data.teams ||
        collectTeams(
          state.data.videos ||
            []
        )
      ).map(
        (team) => team.id
      )
    );

  state.selectedTeams =
    new Set(
      [
        ...state.selectedTeams
      ].filter((id) =>
        availableTeams.has(id)
      )
    );

  const updatedAt =
    $('#updatedAt');

  if (updatedAt) {
    updatedAt.textContent =
      state.data.generated_at
        ? `Dernière collecte : ${formatDate(
            state.data.generated_at
          )}`
        : 'Pas encore de collecte';
  }

  renderAll();
}

/* ============================================================
   EVENTS
   ============================================================ */

$('#search')?.addEventListener(
  'input',
  (event) => {
    state.search =
      event.target.value;

    renderFeed();
  }
);

$('#favoritesToggle')
  ?.addEventListener(
    'click',
    () => {
      state.favoritesOnly =
        !state.favoritesOnly;

      if (
        state.favoritesOnly &&
        !state.selectedTeams.size
      ) {
        alert(
          'Sélectionne au moins une équipe pour utiliser ce filtre.'
        );

        state.favoritesOnly =
          false;

        return;
      }

      saveStore();
      renderAll();
    }
  );

$('#unseenToggle')
  ?.addEventListener(
    'click',
    () => {
      state.unseenOnly =
        !state.unseenOnly;

      saveStore();
      renderAll();
    }
  );

$('#themeBtn')
  ?.addEventListener(
    'click',
    () => {
      state.theme =
        state.theme === 'dark'
          ? 'light'
          : 'dark';

      saveStore();
      applyTheme();
    }
  );

$('#resetBtn')
  ?.addEventListener(
    'click',
    () => {
      localStorage.removeItem(
        STORE_KEY
      );

      state.selectedTeams.clear();
      state.selectedSources.clear();
      state.seen.clear();

      state.favoritesOnly =
        false;

      state.unseenOnly =
        false;

      state.theme =
        'light';

      state.search = '';

      const search =
        $('#search');

      if (search) {
        search.value = '';
      }

      applyTheme();
      renderAll();
    }
  );

boot().catch((error) => {
  console.error(error);

  const empty =
    $('#empty');

  if (empty) {
    empty.classList.remove(
      'hidden'
    );

    const heading =
      empty.querySelector('h3');

    const paragraph =
      empty.querySelector('p');

    if (heading) {
      heading.textContent =
        'Impossible de charger les données.';
    }

    if (paragraph) {
      paragraph.textContent =
        `${error.message}. Vérifie que data/videos.json est bien publié avec le site.`;
    }
  }
});
