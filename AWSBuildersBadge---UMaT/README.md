# BuildersBadge — Builder Card

A club portfolio website for the **AWS Student Builder Group**: each student shows their skills on a customizable builder card, and can reshape it to serve whatever purpose they want — mini portfolio, club ID, project showcase.

## Lesson 1 — clone & customize (mini GitHub test)

1. **Get the repo**
   ```bash
   git clone https://github.com/Hell0Beta/AWSBuildersBadge---UMaT.git
   ```
   (or download the ZIP if `git` feels heavy the first time)

2. **Open the site** — just double-click the HTML file. No installs, no build steps.

3. **Make it yours** — open **`config.json`** and edit:
   - Name, bio, location, "looking for" line, profile photo path
   - Your language breakdown, badges, repo/star counts
   - Links (GitHub, socials) and the builders you've met

4. **Save & refresh** the browser to see your changes.

*(Next lesson: this moves to a simple `config.json` so you won't need to touch the HTML at all.)*

## Connect your GitHub

Each student can connect their card to GitHub with zero build tools or secret keys:
- **Profile details:** Live display name, profile avatar, bio, and public repo counts from GitHub's REST API.
- **Activity grid:** Live 1-year contribution grid matching the card's green palette (levels 0–4), total contribution counter, one column per week, with informative tooltips (`"N contributions on DATE"`).
- **Real-Time Activity Feed:** Live feed showing your latest pushes, commits, and starred repositories with relative timestamps (`2m ago`, `3h ago`).
- **On-Demand Real-Time Sync:** Tap the **"↻ Sync live"** button to bypass local cache and refresh your GitHub stats and commits immediately in real time.
- **Printable QR Badge:** Download your QR badge as a high-resolution PNG image with your name and handle for club meetups.

### 1. Set your username
Open `config.json` and set your username in `profile.username`:
```json
{
  "profile": {
    "username": "your-github-username",
    "name": "Your Name",
    "location": "Accra",
    "lookingFor": "a frontend designer",
    ...
  }
}
```

**How your GitHub account is chosen:** the card connects your **`profile.username`**. Set `"github"` in `config.json` *only* if your GitHub handle differs from your site username (it's a plain string override).

**What's live vs. what you own:**

| GitHub-owned (updates automatically) | Config-owned (you edit) |
|---|---|
| name, bio, avatar, repos, followers, contribution grid, live event feed | location, "looking for", languages, badges, links, connected builders |

When GitHub is unreachable (offline demo, rate limit, `file://`), your `config.json` values are used as the fallback — including name/bio — so the card never breaks. `?u=<username>` on the URL previews anyone's card without editing files.

> **Opening via `file://` (Double-click):** browsers block `fetch('config.json')` on `file://`, so the card shows minimal defaults. For the real card, serve the folder — `python -m http.server` (the banner prints the URL & QR).

### 2. Run locally
Serve the repository directory locally with Python:
```bash
python -m http.server 8000
```
Then open `http://localhost:8000` in your browser (or `http://<your-ip>:8000` on your mobile phone on the same Wi-Fi). Running over HTTP enables `config.json` fetching and camera access.

### 3. Smart cache + Real-Time Sync (no tokens, no rate limits)
- **Classroom Wi-Fi friendly:** Unauthenticated GitHub API calls share a limit of 60 requests per hour per public IP address.
- **Client cache:** Profile and activity data are cached in `localStorage` for **3 hours** to prevent rate limits during workshops.
- **Real-Time Sync:** When you push a commit or star a repo, clicking **"↻ Sync live"** immediately updates your card in real time.
- **Zero tokens:** No personal access tokens or credentials are required or stored in client code.
- **Graceful fallbacks:** If an API call fails, the network is offline, or a username doesn't exist, the card gracefully shows your config name, a placeholder ASCII avatar, and an empty grid with an *"Activity unavailable"* note. The card and scavenger hunt never break.

## GitHub Pages Deployment

The repository includes a GitHub Actions workflow (`.github/workflows/pages.yml`). When you push to your GitHub repository:
1. In your GitHub repo, go to **Settings** ➔ **Pages**.
2. Under **Build and deployment** ➔ **Source**, select **GitHub Actions**.
3. Your builder card will automatically deploy and be live at:
   `https://<your-github-username>.github.io/AWSBuildersBadge---UMaT/`

## The scavenger hunt (first session game)

Every card displays a **real QR code** carrying a text payload `BB1|<username>|<name>`
that any scanner (phone camera app, in-page scanner, hub) can read.

### Hunt Hub mode (multi-laptop session — the main flow)

Since each student runs the site from **their own laptop's** `python -m http.server`,
no single QR page can hand events to another student's browser. Instead, one box in
the room runs the **Hunt Hub** — a tiny portable server — and every card syncs
scans/quiz/trinkets through it:

1. Start the hub: `python hub/hunt_hub.py --port 8788` (stdlib-only, zero deps).
   Add `--room <code>` to keep other badges-out instances from mixing in.
2. Everyone opens the hub page once (`http://<hub-IP>:8788` — or an HTTPS URL) and
   stays on it during the hunt.
3. Point the hub page's in-page scanner at another builder's card QR *(this is where
   the phone camera helps: the hub runs over HTTPS it can use the phone camera too)*.
   The hub shows the **20s quiz** (same cloud/AWS/AI bank); answering correctly fills
   a trinket slot → the hub shows live trinket slots + hunt targets.
   Students add one line to their `config.json` —
   ```json
   "hub": "http://<hub-ip>:8788"
   ```
   Their own card then long-polls the hub every 4s: connected builders, trinkets won,
   and hunt toggle sync automatically onto their own site (and their card QR stays
   in sync — nothing else to edit).
4. Hunt mode on the hub: **Start hunt** gives 3 random trinket targets; collect all
   3 to win. Hub-less fallback: leave `"hub"` empty and everything works as before.

See `hub/API.md` for the full API contract and hosting recipes (AWS EC2, GitHub
Pages UI, Cloudflare Worker port).

### One-laptop / hub-less flow (existing behaviour)

1. Open the site and flip the **Scavenger hunt mode** toggle (🔍 icon) inside the *Scan to connect* card — three trinket slots appear. Each toggle picks a **fresh random set of 3 trinkets** from a pool of 7 and clears previous progress.
2. **On a phone (primary):** point your phone's **native camera app** at another builder's card QR — it navigates you to the site and **auto-connects that builder** (`?u=` URL payloads are still parsed historically; the QR itself now carries the `BB1` text payload). The link is stripped from the address bar afterwards, so refreshing won't re-connect.
3. **On a laptop / secure context:** tap **Scan someone** (bottom bar) — it opens the camera, hunt on or off. Allow camera access and point it at another card's QR.
   On an insecure origin (plain `http://` LAN IP — the only way phones usually load a local server) the in-page camera is unavailable by browser rules; tap Scan and you'll see *"Use your phone camera instead — using insecure origin."*
4. **Hunt on:** connecting that builder starts a **20-second multiple-choice question** (cloud / AWS / AI / backend) locally on the card. Correct → a random missing trinket fills a slot. Wrong/time-up → forfeit; re-scan the same person to try again.
5. **Hunt off:** connecting simply adds the builder to your connected list (camera or link, either way).
6. Collect **all 3 trinkets** to win the hunt. Progress saves in the browser; refresh won't lose it. "Reset hunt" (or another toggle) clears trinkets and gives new ones.

**Important:** camera scanning needs a *secure context*. Serve the folder locally before playing:

```bash
python install_banner.py      # once per machine — installs the server banner
python -m http.server         # then use the plain command as always
```

Running `python -m http.server` inside this folder now prints the **AWS STUDENT BADGE** banner: block art, the `http://localhost:<port>` URL, your **LAN URL** for phones, and a **scannable QR code** of the LAN address. Point every phone at that QR (same Wi-Fi required). Optional QR art needs one extra package:

```bash
pip install qrcode
```

- Uninstall the banner: `python install_banner.py --remove`
- Silence it temporarily: set `BUILDERBADGE_NOBANNER=1` before running
- Windows Firewall may prompt once when a phone first opens the LAN URL — choose *Allow on private networks*
- On machines without the install, plain `python -m http.server` still works normally (just without the banner)

For a one-phone demo you can still double-click the file; camera scanning will just be unavailable.

## Repo layout

```
BuildersBadge/
├── .github/workflows/pages.yml                  ← 1-click GitHub Pages deployment workflow
├── config.json                                  ← student card configuration (source of truth)
├── index.html                                   ← the live site (builder card + QR hunt)
├── libs/                                        ← vendored libraries & helpers
│   ├── github-profile.js                        ← GitHub API profile, activity & real-time events helper
│   ├── qrcode-generator.min.js                  ← offline QR code generation
│   └── jsqr.min.js                              ← in-browser camera QR code decoding
├── task.md                                      ← task board
└── README.md
```

## For maintainers

- Task board: see `task.md`
- QR payload format: card QRs carry `BB1|<username>|<name>` (`qrPayload()`); `handlePayload()` / `autoLink()` still parse legacy `?u=<username>&n=<name>` URLs for one-laptop demos. In hub mode (`"hub"` set in `config.json`) scans + quiz + trinkets flow through the hub instead of localStorage — see `hub/API.md`; the hub reference implementation is `hunt_hub.py` and the contract test checklist lives there
- The quiz bank is the `QUIZ` array in `index.html` (~22 questions) — for hub mode, keep both copies in sync (the hub reads its own copy in `hunt_hub.py` + `hub/public/index.html`); add or edit questions in all three
- Trinket pool: `TRK` array in `index.html` (7 inline SVG icons; each toggle picks 3 targets). Hunt state key in `localStorage`: `builderHunt.v2` (old v1 data is ignored); hub cursor/token keys: `bbHub.cursor` / `bbHub.tok`
- Hub contract test: `python hub/hunt_hub.py` then walk the endpoint table in `hub/API.md` (or boot the page and point it at `?api=`); the reference server passes an end-to-end contract suite covering register→scan→quiz→trinket→cursor denies + CORS + room gate
- Camera test tip: `http://localhost:8000`; phones on the same Wi-Fi use `http://<your-IP>:8000` (camera requires localhost or HTTPS on some browsers)
