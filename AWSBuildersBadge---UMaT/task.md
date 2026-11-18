# Tasks — BuildersBadge (Builder Card)

A club portfolio website each student clones, customizes, and makes their own.
Lesson 1 uses the repo as a mini test of GitHub conversancy (clone → edit → view).

## Done

- [x] **Live GitHub profile & activity grid (`libs/github-profile.js`)** — students connect GitHub with zero config friction:
  - [x] ~~Add `"github"` username field to `config.json` with fallback `window.INLINE_CONFIG` script object for `file://` offline browsing~~ — superseded: GitHub account is now `profile.username` (optional `"github"` string override); `INLINE_CONFIG` removed, minimal `DEF` defaults serve the `file://` case
  - [x] Live GitHub profile (name, avatar_url, public repos, bio) with fallback to config values and ASCII avatar
  - [x] Live 1-year contribution grid (`jogruber` API, levels 0-4, date tooltips) with "Activity unavailable" empty state fallback
  - [x] Real-time public activity feed (`/users/<username>/events/public`) with relative timestamps (`2m ago`, `1d ago`)
  - [x] On-demand "↻ Sync live" button with pulsing live indicator to refresh activity in real-time
  - [x] Total contribution count stat badge in Activity header
  - [x] High-resolution printable PNG QR badge exporter with student handle & name
  - [x] URL query param preview (`?u=<username>`) for instant mentor/student profile switching
  - [x] 3-hour client-side `localStorage` cache to prevent unauthenticated IP rate limits (60 req/hr) on shared class Wi-Fi
  - [x] Stretch hooks / TODO comments for students (top languages, pinned repos, custom themes)
- [x] **Deployment story: GitHub Pages (`.github/workflows/pages.yml`)** — automated static deployment when pushed to GitHub
- [x] **Unified `card.html` + `index.html` into one page (`index.html`)** — config layer, real QR, scan, hunt & quiz all live together; `card.html` deleted
- [x] Sections grid: on desktop (>1200px, 2-column mode) a section sitting alone in a row spans the full row (`reflowWide()`, re-runs on load/drag/keyboard reorder/resize)
- [x] Builder Card mobile prototype (sample data, drag-to-reorder sections, photo upload preview)
- [x] **QR scavenger hunt** (QR task owner) — `index.html` + vendored `libs/`:
  - [x] Real QR code generated from the builder's payload — a URL (`?u=<username>&n=<name>`) so a **phone's native camera** navigates to the site and auto-connects that builder (`autoLink`), with legacy `BB1|<u>|<n>` text kept for `file://` demos; the in-page jsQR scanner parses both
  - [x] **Hunt mode toggle** inside the Scan-to-connect card → card expands with 3 trinket slots (inline SVG icons)
  - [x] "Scan someone" (hunt on) → camera access (`getUserMedia`) + in-browser decode via vendored jsQR
  - [x] Valid scan → builder added to connected list → in hunt mode the section swaps to a **20s countdown** + MCQ (cloud / AI / AWS / backend / DevOps, beginner + intermediate, 22-question bank, options shuffled)
  - [x] Correct answer → random missing trinket awarded → slot fills; all 3 = win popup
  - [x] Wrong / timeout → forfeit; that builder stays un-trinketed so you can re-scan them again
  - [x] Re-scan of a builder who already gave a trinket → connection popup only
  - [x] "Scan someone" always opens the camera (legacy random-popup scan removed); hunt-off scans just connect builders
  - [x] Hunt toggle re-rolls the 3 target trinkets each toggle from a 7-icon pool and clears progress (schema v2, old v1 data ignored)
  - [x] Camera playback fixed (explicit `.play()` + `autoplay`) — had shown only the first frozen frame
  - [x] Big full-screen 3-2-1 countdown before each question (options locked until it ends)
  - [x] Toast notifications: builder added to connected list; scan rejected because a trinket was already taken from that builder
  - [x] 8s "hold the QR steady" hint while scanning
  - [x] Progress (hunt on/off, trinkets, connected builders) persists in `localStorage`; "Reset hunt" clears it
  - [x] Works fully offline (both libs vendored under `libs/`); camera needs `localhost` or `https` → run `python -m http.server`
- [x] **Hunt Hub** — one box in the room runs a tiny server (`python hub/hunt_hub.py`, stdlib-only, SQLite) that
  every card syncs through, so per-student `http.server` instances on different laptops can play the hunt together
  (a pure QR handoff can't: each student's QR points at *their own* laptop, and browsers can't push events into
  another origin's localStorage):
  - [x] Card QR payload is now plain text `BB1|<username>|<name>` (the hub page's in-page scanner reads any card QR,
    and legacy `?u=&n=` URL payloads stay parsed for one-laptop demos)
  - [x] Hub UI (`hub/public/index.html`: dark terminal-styled page with inline jsQR scanner, attribution form,
    live trinket slots, hunt start/stop, server-side 20s quiz countdown bar) — camera needs HTTPS on the hub host
  - [x] Student's own site syncs (`config.json` `"hub": "<url>"`): registers under `profile.username`, long-polls
    the hub every 4s and applies `connect` / `trinket` / `scanned` events locally; hunt toggle pushes to the hub
    instead of rolling local targets; hub-less fallback unchanged
  - [x] Hub API contract documented in `hub/API.md` (register/state/scan/quiz + 5 semantics + room code gate + CORS)
    with hosting recipes: AWS EC2 (your target), GitHub Pages split plane, Cloudflare Worker port checklist
  - [x] Contract test suite: 27/27 PASS end-to-end over real HTTP (register idempotency, scan self/dup/garbage
    rejects, event routing (connect → scanner, scanned → owner), hunt targets 3-of-7, quiz resume + late/timeout,
    trinket award + cursor no-redelivery, room gate, CORS headers)

## In progress

- [x] **JSON config file (`config.json`)** — students customize by editing one file instead of the HTML:
  - [x] Profile picture (file path), name, bio, location, "looking for"
  - [x] Repo/star counts, language breakdown, badges
  - [x] Site loads the config at runtime (with fallback sample data)
- [x] Wire the QR/quiz engine to `config.json`: the engine already reads `window.CFG` (`CFG.profile.name`, `CFG.profile.username`) — the refactor only has to set `window.CFG` and everything updates
- [x] **`python install_banner.py` server banner** — once installed, plain `python -m http.server` in this folder
  prints AWS STUDENT BADGE block art, localhost + LAN URLs, and a scannable terminal QR of the LAN address
  (pip `qrcode` for the QR part; `--remove` / `BUILDERBADGE_NOBANNER=1` available; folder-marker gated so
  other http.server projects are unaffected)
- [x] **Config layer cleanup + honest live stats** — one source of truth for identity data:
  - [x] Account resolution: GitHub account = `profile.username` (optional `"github"` string override); an empty `""` no longer silently disables sync
  - [x] **Precedence rules made explicit** (README table + code comment): GitHub-owned = name/bio/avatar/repos/followers/activity grid/feed; config-owned = location/lookingFor/languages/badges/links/builders (`syncLiveActivity` hidden guards removed)
  - [x] Hardcoded "stars" replaced with **live followers** (same `/users/<name>` request — zero extra API calls)
  - [x] `window.INLINE_CONFIG` deleted (the third duplicate config dictionary); `DEF` slimmed to structural defaults; dead `graph()` placeholder removed
  - [x] Verified: merge harness 11/11, real-account fetch (repos + followers land in the card), `node --check`, orphan audit clean, HTTP smoke

## To do

- [x] Contact/links section (GitHub, socials) driven by config
- [ ] Deployment story: GitHub Pages so each student's card is live at a URL (partly superseded by the Hunt Hub — one hub host does the job; still nice for pure-public card URLs)
- [x] Replace placeholder contribution graph with live GitHub activity grid (levels 0-4, date tooltips)
- [ ] Lesson 1 setup: exact clone instructions + first task for students in README
- [ ] Playtest the hunt with real phones: hub session across ≥2 laptops + phones (scan a card QR on one laptop from the hub page on another, quiz on hub, trinket lands on the student's own site over the 4s poll); check emoji/cp1252 consoles don't break the hub banner, and `--room` keeps two rooms apart
- [ ] Replace remaining placeholder gimmicks: fake contribution graph, overlap popup's random data (now wired for demo use in hunt mode)
- [ ] Playtest the hunt with real phones: scanning a QR displayed on another phone screen (brightness/distance), review question difficulty mix
- [ ] Replace remaining placeholder gimmicks: overlap popup's random data (now wired for demo use in hunt mode)
