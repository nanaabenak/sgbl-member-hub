# Hunt Hub — API contract v1

The hub is a tiny stateful service that sits between every student's own
 BuildersBadge site (`http://<student-ip>:8000`, each running their own
 `config.json`) and the scavenger hunt's cross-student bookkeeping.

Anything that implements this contract can host the hub. The repo ships a
**reference implementation**: `hunt_hub.py` — stdlib-only Python 3.10+, zero
dependencies, SQLite storage, serves the UI from `./public`.

```
hunt_hub.py  --port 8788  [--room CODE]  [--public DIR]  [--db FILE]
```

## Concepts

- **Session** — a username gets a random 32-hex **token** on register. The token
  identifies "this person" to the hub with no passwords. Registration is
  idempotent: same username → same token forever (until the room resets).
- **Event** — an append-only row `{id, receiver, type, ts, ...payload}`.
  Types: `connect` (r connected with owner), `scanned` (owner was scanned by r),
  `trinket` (r earned trinketId with owner). Events are fetched by **cursor**
  (last id seen) and expire after **24h**.
- **Quiz** — the hub holds the question bank, the answer, and a server-side 20s
  deadline (`endsAt`), so tab re-opening can't cheat the timer.
- **Trinkets** — fixed pool: `cloud chip srv db branch zap shield`.
  Hunt mode assigns a fresh random set of 3 targets; the hub tracks `won`.
- **Room** — optional `--room CODE`: every state-changing call must pass
  `?room=CODE` when set. Open by default.

Transport: all JSON. CORS on `/api/*` is `*` (the hub page or a student's page
on `http://<any-lan-ip>` must be able to call it, so browsers require `*`).
Errors: HTTP 4xx/5xx + `{"ok": false, "error": "..."}`.

Payload parsing (what `/api/scan` accepts as `raw`):
- `BB1|<username>|<name>` — text payload from every card QR (primary)
- URL form `...?u=<username>&n=<name>` — legacy/auxiliary, parsed when present

## Endpoints

| Route | Method | Body / query | Returns |
|---|---|---|---|
| `/api/health` | GET | – | `{ok, name, room, trinkets[], quizSeconds}` |
| `/api/register` | POST | `{username, name}` (+`?room`) | `{ok, token, username, name, hunt}` |
| `/api/state` | GET | `?token&cursor` | `{ok, username, name, hunt:{on,targets,won}, cursor, events[]}` |
| `/api/scan` | POST | `{token, raw}` (+`?room`) | `{ok, owner, name, hunt}` — emits `connect` (deduped per owner per 24h) and `scanned` to owner if owner has a session |
| `/api/hunt/start` | POST | `{token}` (+`?room`) | `{ok, hunt}` — on, fresh 3 targets, cleared `won` |
| `/api/hunt/stop` | POST | `{token}` (+`?room`) | `{ok, hunt}` — off |
| `/api/quiz` | GET | `?token&owner` | `{ok, qid, category, question, options[4], endsAt}` — refuses if hunt off / all collected / own card; resuming returns the **same** pending question |
| `/api/answer` | POST | `{token, qid, choice}` | `{ok, result: 'correct'\|'wrong'\|'late', trinket?}` — on correct awards a random missing target and emits `trinket` |

Semantics worth preserving in any port:

1. `/api/register` must be idempotent per username.
2. `/api/scan` must not emit a duplicate `connect` for the same (receiver, owner) inside 24h, and must refuse the scanner scanning their own card.
3. `/api/quiz` must resume an existing pending quiz (same qid + same question) instead of rolling a new one.
4. `/api/answer` decisions are made server-side against the stored answer and `endsAt`; `late` beats `wrong` after the deadline.
5. Trinkets are awarded only from the receiver's own `targets` minus `won`.

## How the Builder Card site consumes it

Students add one line in their `config.json` (empty per default):

```json
"hub": "https://<your-hub-host>/"
```

On load the site registers under its own `profile.username`, then polls
`/api/state` every 4s with cursor `localStorage["bbHub.cursor"]`, mapping events:

- `connect` → existing `connect(owner, name)` card logic (hunt quiz branch is
  bypassed in hub mode — the quiz happens on the hub page)
- `trinket` → marks that builder's slot and the trinket, `saveHunt()` repaint
- `hunt` state → the local hunt mirror follows the hub (toggles push to the
  hub instead of rolling local targets)

## Hosting recipes

### A) Laptop / Raspberry Pi / any box (default, offline LAN)
```
python hunt_hub.py --port 8788
```
Phones open `http://<this-box-LAN-IP>:8788`. Camera works only over HTTPS —
for demos, note the hub page is then insecure-origin too (camera blocked there),
so run yourself behind HTTPS (recipe B/C) if in-page scanning is wanted.

### B) AWS EC2 (your target)
1. Security group: inbound TCP 8788 (later 443) from `0.0.0.0/0` or your hotspot range.
2. OS: any; `sudo apt install python3` equivalent — **stdlib only, no deps**.
3. Copy the `hub/` folder; `python3 hunt_hub.py --port 8788 --room <code>`.
4. Systemd unit for auto-restart:
   ```ini
   [Unit]
   Description=BuildersBadge Hunt Hub
   [Service]
   ExecStart=/usr/bin/python3 /opt/hub/hunt_hub.py --port 8788 --room <code>
   Restart=always
   [Install]
   WantedBy=multi-user.target
   ```
5. **HTTPS for the camera**: point a DNS name (A record → the instance IP), then
   `certbot --nginx`/Caddy reverse proxy 443→8788, and open the hub via
   `https://<your-domain>/`. Students' `config.json` gets that URL.

State lives in `hunt_hub.db` on the instance disk — survive by snapshotting or
just accept per-session resets.

### C) GitHub Pages as the hub UI (split plane)
`hub/public/*` is pure static — host on Pages. The UI discovers its API base
in this order: `?api=<url>` query param (persisted to `localStorage`) →
same-origin as fallback. **Constraint:** a `https` page may not fetch an
`http` API (mixed content) — so this recipe requires an HTTPS API (B with
certbot, D, etc.) to keep the camera path working.

### D) Cloudflare Worker port (checklist)
Implement the table above with D1 (or a SQLite-backed Durable Object):
`sessions`, `events` (AUTOINCREMENT id), `quiz`; serve `public/` as static
assets; keep the five semantics; same CORS. The card site code does not change.

### E) One-laptop demo fallback (no hub)
Keep `config.json`'s `"hub": ""`. Everything works exactly as it did before: local
quiz on the site itself, in-page scanner where the secure context exists.
