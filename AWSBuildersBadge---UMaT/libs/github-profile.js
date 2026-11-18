/**
 * AWS Student Builder Group - GitHub Profile & Activity Helper
 * ==============================================================
 * This module connects a builder's card to live GitHub stats:
 * 1. Profile information (name, avatar, repos) from the official GitHub REST API.
 * 2. Activity graph (annual contribution levels) from jogruber's contributions API.
 * 3. Real-time public activity feed (/events/public) showing latest pushes & stars.
 * 
 * DESIGN PRINCIPLES:
 * - Simple & readable: Plain modern JavaScript without any external frameworks.
 * - Resilient & safe: No API keys or tokens are stored or transmitted.
 * - Cache-first with Live Sync: Stores data in localStorage to protect shared
 *   classroom Wi-Fi against unauthenticated rate limits (60 req/hr), while
 *   providing on-demand real-time sync.
 */

(function (window) {
  'use strict';

  // Cache duration: 3 hours for profile/contributions, 5 minutes for real-time events
  const CACHE_TTL_MS = 3 * 60 * 60 * 1000;
  const EVENTS_CACHE_TTL_MS = 5 * 60 * 1000;

  /**
   * Helper to retrieve cached data from browser localStorage.
   * If the cache item exists and is not expired, returns the data; otherwise null.
   *
   * @param {string} key
   * @param {number} ttl
   * @returns {any|null}
   */
  function getCached(key, ttl = CACHE_TTL_MS) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return null;
      const record = JSON.parse(raw);
      if (record && record.timestamp && (Date.now() - record.timestamp < ttl)) {
        return record.data;
      }
    } catch (err) {
      console.warn('[GitHubProfile] Could not read cache for key:', key, err);
    }
    return null;
  }

  /**
   * Helper to write data into browser localStorage with current timestamp.
   *
   * @param {string} key
   * @param {any} data
   */
  function setCache(key, data) {
    try {
      const record = {
        timestamp: Date.now(),
        data: data
      };
      localStorage.setItem(key, JSON.stringify(record));
    } catch (err) {
      console.warn('[GitHubProfile] Could not write cache for key:', key, err);
    }
  }

  /**
   * Clear cached data for a specific user to force real-time sync.
   *
   * @param {string} username
   */
  function clearUserCache(username) {
    const cleanUser = (username || '').trim().toLowerCase();
    if (!cleanUser) return;
    try {
      localStorage.removeItem('gh_profile_' + cleanUser);
      localStorage.removeItem('gh_contrib_' + cleanUser);
      localStorage.removeItem('gh_events_' + cleanUser);
    } catch (_) {}
  }

  /**
   * Format relative time (e.g. "2m ago", "3h ago", "2d ago").
   *
   * @param {string} dateStr
   * @returns {string}
   */
  function formatTimeAgo(dateStr) {
    if (!dateStr) return '';
    const diff = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    if (diff < 2592000) return Math.floor(diff / 86400) + 'd ago';
    return Math.floor(diff / 2592000) + 'mo ago';
  }

  /**
   * Fetch a GitHub user profile by username.
   * Uses https://api.github.com/users/<username>
   *
   * @param {string} username
   * @param {boolean} forceRefresh
   * @returns {Promise<{name: string, login: string, avatarUrl: string, bio: string|null, publicRepos: number, followers: number}|null>}
   */
  async function fetchUserProfile(username, forceRefresh = false) {
    const cleanUser = (username || '').trim();
    if (!cleanUser) return null;

    const cacheKey = 'gh_profile_' + cleanUser.toLowerCase();
    if (!forceRefresh) {
      const cached = getCached(cacheKey);
      if (cached) return cached;
    }

    try {
      const response = await fetch('https://api.github.com/users/' + encodeURIComponent(cleanUser));
      if (!response.ok) {
        console.warn(`[GitHubProfile] GitHub API returned status ${response.status} for user: ${cleanUser}`);
        try {
          const raw = localStorage.getItem(cacheKey);
          if (raw) {
            const stale = JSON.parse(raw);
            if (stale && stale.data) return stale.data;
          }
        } catch (_) {}
        return null;
      }

      const json = await response.json();
      const profileData = {
        login: json.login || cleanUser,
        name: json.name || json.login || cleanUser,
        avatarUrl: json.avatar_url || '',
        bio: json.bio || null,
        publicRepos: typeof json.public_repos === 'number' ? json.public_repos : null,
        followers: typeof json.followers === 'number' ? json.followers : null
      };

      setCache(cacheKey, profileData);
      return profileData;
    } catch (err) {
      console.warn('[GitHubProfile] Network error while fetching user profile:', err);
      try {
        const raw = localStorage.getItem(cacheKey);
        if (raw) {
          const stale = JSON.parse(raw);
          if (stale && stale.data) return stale.data;
        }
      } catch (_) {}
      return null;
    }
  }

  /**
   * Fetch annual contribution activity for a GitHub user.
   * Uses https://github-contributions-api.jogruber.de/v4/<username>?y=last
   *
   * @param {string} username
   * @param {boolean} forceRefresh
   * @returns {Promise<{contributions: Array<{date: string, count: number, level: number}>, total: number}|null>}
   */
  async function fetchUserContributions(username, forceRefresh = false) {
    const cleanUser = (username || '').trim();
    if (!cleanUser) return null;

    const cacheKey = 'gh_contrib_' + cleanUser.toLowerCase();
    if (!forceRefresh) {
      const cached = getCached(cacheKey);
      if (cached) {
        if (Array.isArray(cached)) {
          return {
            contributions: cached,
            total: cached.reduce((sum, item) => sum + (item.count || 0), 0)
          };
        }
        return cached;
      }
    }

    try {
      const response = await fetch('https://github-contributions-api.jogruber.de/v4/' + encodeURIComponent(cleanUser) + '?y=last');
      if (!response.ok) {
        console.warn(`[GitHubProfile] Contributions API returned status ${response.status} for user: ${cleanUser}`);
        try {
          const raw = localStorage.getItem(cacheKey);
          if (raw) {
            const stale = JSON.parse(raw);
            if (stale && stale.data) {
              if (Array.isArray(stale.data)) {
                return {
                  contributions: stale.data,
                  total: stale.data.reduce((sum, item) => sum + (item.count || 0), 0)
                };
              }
              return stale.data;
            }
          }
        } catch (_) {}
        return null;
      }

      const json = await response.json();
      if (!json || !Array.isArray(json.contributions)) {
        return null;
      }

      // Map to ensure uniform items with date, count, and level (0 to 4)
      const contributions = json.contributions.map(item => ({
        date: item.date,
        count: typeof item.count === 'number' ? item.count : 0,
        level: typeof item.level === 'number' ? Math.min(4, Math.max(0, item.level)) : 0
      }));

      const totalLastYear = json.total && typeof json.total.lastYear === 'number'
        ? json.total.lastYear
        : contributions.reduce((sum, item) => sum + (item.count || 0), 0);

      const result = {
        total: totalLastYear,
        contributions: contributions
      };

      setCache(cacheKey, result);
      return result;
    } catch (err) {
      console.warn('[GitHubProfile] Network error while fetching contributions:', err);
      try {
        const raw = localStorage.getItem(cacheKey);
        if (raw) {
          const stale = JSON.parse(raw);
          if (stale && stale.data) {
            if (Array.isArray(stale.data)) {
              return {
                contributions: stale.data,
                total: stale.data.reduce((sum, item) => sum + (item.count || 0), 0)
              };
            }
            return stale.data;
          }
        }
      } catch (_) {}
      return null;
    }
  }

  /**
   * Fetch real-time public events for a GitHub user.
   * Uses https://api.github.com/users/<username>/events/public?per_page=8
   *
   * @param {string} username
   * @param {boolean} forceRefresh
   * @returns {Promise<Array<{id: string, type: string, action: string, detail: string, repoName: string, repoUrl: string, timeAgo: string, date: string}>>}
   */
  async function fetchUserEvents(username, forceRefresh = false) {
    const cleanUser = (username || '').trim();
    if (!cleanUser) return [];

    const cacheKey = 'gh_events_' + cleanUser.toLowerCase();
    if (!forceRefresh) {
      const cached = getCached(cacheKey, EVENTS_CACHE_TTL_MS);
      if (cached && Array.isArray(cached)) return cached;
    }

    try {
      const response = await fetch('https://api.github.com/users/' + encodeURIComponent(cleanUser) + '/events/public?per_page=8');
      if (!response.ok) return [];
      const json = await response.json();
      if (!Array.isArray(json)) return [];

      const parsed = json.slice(0, 5).map(ev => {
        let action = 'Activity';
        let detail = '';
        const repoName = ev.repo ? ev.repo.name : '';
        const repoUrl = repoName ? 'https://github.com/' + repoName : '#';

        if (ev.type === 'PushEvent') {
          const count = (ev.payload && ev.payload.commits && ev.payload.commits.length) || 1;
          const branch = (ev.payload && ev.payload.ref ? ev.payload.ref.replace('refs/heads/', '') : 'main');
          action = 'Pushed ' + count + (count === 1 ? ' commit' : ' commits');
          detail = branch;
        } else if (ev.type === 'WatchEvent') {
          action = 'Starred repository';
        } else if (ev.type === 'CreateEvent') {
          action = 'Created ' + (ev.payload && ev.payload.ref_type ? ev.payload.ref_type : 'branch');
          detail = ev.payload && ev.payload.ref ? ev.payload.ref : '';
        } else if (ev.type === 'PullRequestEvent') {
          action = (ev.payload && ev.payload.action ? ev.payload.action : 'Opened') + ' pull request';
        } else if (ev.type === 'ForkEvent') {
          action = 'Forked repository';
        } else if (ev.type === 'IssuesEvent') {
          action = (ev.payload && ev.payload.action ? ev.payload.action : 'Updated') + ' issue';
        }

        return {
          id: ev.id,
          type: ev.type,
          action: action,
          detail: detail,
          repoName: repoName,
          repoUrl: repoUrl,
          timeAgo: formatTimeAgo(ev.created_at),
          date: ev.created_at
        };
      });

      setCache(cacheKey, parsed);
      return parsed;
    } catch (err) {
      console.warn('[GitHubProfile] Could not fetch real-time events:', err);
      return [];
    }
  }

  /**
   * Format the tooltip text for a contribution cell.
   * e.g. "0 contributions on 2026-10-25" or "3 contributions on 2026-10-26"
   *
   * @param {number} count
   * @param {string} date
   * @returns {string}
   */
  function formatTooltip(count, date) {
    const noun = count === 1 ? 'contribution' : 'contributions';
    return `${count} ${noun} on ${date}`;
  }

  // Expose methods on window.GitHubProfile
  window.GitHubProfile = {
    fetchProfile: fetchUserProfile,
    fetchContributions: fetchUserContributions,
    fetchEvents: fetchUserEvents,
    clearUserCache: clearUserCache,
    formatTimeAgo: formatTimeAgo,
    formatTooltip: formatTooltip,
    CACHE_TTL_MS: CACHE_TTL_MS,
    EVENTS_CACHE_TTL_MS: EVENTS_CACHE_TTL_MS
  };

  /* ===========================================================================
   * STRETCH HOOKS FOR STUDENTS (TODO - Ideas for extending your builder card):
   * ===========================================================================
   * 
   * 1. TOP LANGUAGES:
   *    TODO: Fetch https://api.github.com/users/<username>/repos?per_page=100
   *    Count occurrences of `repo.language` across your public repositories,
   *    and calculate percentages to render custom language bars!
   *
   * 2. PINNED REPOSITORIES:
   *    TODO: Showcase your proudest projects! You can use an open API like
   *    https://github-pinned-repositories.ercany/api/?username=<username>
   *    or the GitHub GraphQL API to display project cards with star counts.
   *
   * 3. CARD THEMES:
   *    TODO: Add a theme picker (e.g. Cyberpunk, Synthwave, AWS Orange, Dark/Light)
   *    by swapping CSS variables (--bg, --g, --cell, --line) in :root!
   * ===========================================================================
   */

})(window);
