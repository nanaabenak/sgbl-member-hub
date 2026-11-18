"""BuildersBadge Hunt Hub — portable reference implementation of the hub API contract.

Stdlib only (http.server + sqlite3), so it runs anywhere Python 3.10+ does:
a laptop, an AWS EC2 instance, a Raspberry Pi. See API.md for the contract
and hosting recipes.

Quickstart:
    python hunt_hub.py --port 8788 --room my-code

    python hunt_hub.py --help

Test tuning:
    BB_TEST_QUIZ_SECONDS=1 python hunt_hub.py --port 8788
(useful for automated tests; never set in real sessions)

Storage is a single SQLite file (default hunt_hub.db in this folder).
Static UI is served from ./public.
"""

import argparse
import json
import os
import re
import secrets
import random
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
TRINKETS = ['cloud', 'chip', 'srv', 'db', 'branch', 'zap', 'shield']
QUIZ = [
    {'c': 'AWS', 'q': 'Which AWS service lets you run code without provisioning or managing servers?', 'o': ['Lambda', 'EC2', 'S3', 'Redshift'], 'a': 0},
    {'c': 'AWS', 'q': "Which service is Amazon's object storage?", 'o': ['S3', 'EBS', 'RDS', 'SQS'], 'a': 0},
    {'c': 'AWS', 'q': 'What does IAM primarily manage?', 'o': ['Access and permissions', 'Image assets', 'Procurement and invoices', 'Instance autoscaling'], 'a': 0},
    {'c': 'AWS', 'q': 'Which feature keeps EC2 instances available as demand changes?', 'o': ['Auto Scaling', 'Route 53 zones', 'Kinesis streams', 'Snowball jobs'], 'a': 0},
    {'c': 'AWS', 'q': 'You want to store media and serve it fast worldwide. Best combo?', 'o': ['S3 + CloudFront', 'RDS + SES', 'EC2 + EBS', 'Lambda + SNS'], 'a': 0},
    {'c': 'AWS', 'q': 'Which managed service fits relational (SQL) workloads?', 'o': ['RDS', 'S3', 'SES', 'CloudFront'], 'a': 0},
    {'c': 'AWS', 'q': 'Who patches the operating system of an on-demand EC2 instance?', 'o': ['The customer', 'AWS, always', 'Nobody', 'Lambda'], 'a': 0},
    {'c': 'Cloud', 'q': "'Serverless' in cloud computing means…", 'o': ['You do not provision or manage the servers', 'There are literally no servers', 'Code only runs offline', 'Servers are always free'], 'a': 0},
    {'c': 'Cloud', 'q': 'Uniform scaling up/out in the cloud means…', 'o': ['Adding resources to handle demand growth', 'Manually reinstalling bigger machines daily', 'Data going offline', 'Deleting ignored backups'], 'a': 0},
    {'c': 'Cloud', 'q': 'Infrastructure as Code (IaC) exists to…', 'o': ['Define infrastructure in versionable files', 'Encrypt every packet', 'Cache static assets', 'Send transactional email'], 'a': 0},
    {'c': 'Cloud', 'q': 'High availability means…', 'o': ['The system stays usable through failures', 'Bandwidth is very high', 'Backups are deleted', 'Idle servers are extra'], 'a': 0},
    {'c': 'Backend', 'q': 'What does HTTP status 404 mean?', 'o': ['Not found', 'Created', 'Unauthorized', 'Server error'], 'a': 0},
    {'c': 'Backend', 'q': 'A POST that creates a resource usually answers…', 'o': ['201 Created', '302 Found', '401 Unauthorized', '503 Service Unavailable'], 'a': 0},
    {'c': 'Backend', 'q': 'Which one is NOT a database?', 'o': ['Kubernetes', 'MongoDB', 'PostgreSQL', 'Redis'], 'a': 0},
    {'c': 'Backend', 'q': 'In a REST API, GET /users/42 should…', 'o': ['Return that single user', 'Create user 42', 'Delete user 42', 'Reset a password'], 'a': 0},
    {'c': 'Backend', 'q': 'A token issued at login that is sent on later requests is normally used for…', 'o': ['Authentication', 'Caching', 'Rate limiting', 'Load balancing'], 'a': 0},
    {'c': 'AI', 'q': 'A machine-learning model mostly "learns" from…', 'o': ['Data', 'Batteries', 'The browser console', 'Ethernet cables'], 'a': 0},
    {'c': 'AI', 'q': 'Generative AI is used to…', 'o': ['Create new text, images or code', 'Only sort spreadsheets', 'Print ID cards', 'Refill paper trays'], 'a': 0},
    {'c': 'AI', 'q': 'Running a trained model to get answers is called…', 'o': ['Inference', 'Labeling', 'Rendering', 'Compression'], 'a': 0},
    {'c': 'AWS', 'q': 'What does CloudFront do?', 'o': ['Delivers content from edge locations', 'Encrypts data at rest', 'Runs Python handlers', 'Sends marketing emails'], 'a': 0},
    {'c': 'DevOps', 'q': 'A container image is…', 'o': ['A packaged app plus its dependencies', 'A screenshot of a server', 'An OS licence file', 'A CPU usage chart'], 'a': 0},
    {'c': 'DevOps', 'q': 'CI/CD primarily exists to…', 'o': ['Ship code changes safely and often', 'Design logos', 'Store coffee preferences', 'Mute alarms'], 'a': 0},
]

ARGS = None
DB = None
LOCK = threading.RLock()

USERNAME_RE = re.compile(r'^[\w.\-]{1,32}$')
NAME_RE = re.compile(r'^.{1,64}$', re.S)
TOKEN_RE = re.compile(r'^[0-9a-f]{16,64}$')
QUIZ_SECONDS = float(os.environ.get('BB_TEST_QUIZ_SECONDS', 20))
EVENT_TTL = 24 * 3600
QUIZ_TTL = 2 * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  hunt_on INTEGER NOT NULL DEFAULT 0,
  targets TEXT NOT NULL DEFAULT '[]',
  won TEXT NOT NULL DEFAULT '[]',
  created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  receiver TEXT NOT NULL,
  type TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  room TEXT NOT NULL DEFAULT '',
  ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_receiver_ts ON events(receiver, ts);
CREATE TABLE IF NOT EXISTS quiz (
  qid TEXT PRIMARY KEY,
  receiver TEXT NOT NULL,
  owner TEXT NOT NULL,
  qidx INTEGER NOT NULL,
  answer INTEGER NOT NULL,
  ends REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  ts REAL NOT NULL
);
"""


def db():
    global DB
    if DB is None:
        DB = sqlite3.connect(ARGS.db, check_same_thread=False)
        DB.row_factory = sqlite3.Row
        DB.executescript(SCHEMA)
    return DB


def fail(code, msg):
    return code, {'ok': False, 'error': msg}


def parse_payload(raw):
    d = (raw or '').strip()
    if not d:
        return None, ''
    m = re.match(r'^BB1\|([^|]{1,32})\|([^|]{1,64})$', d, re.S)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    if re.match(r'^https?://', d, re.I):
        try:
            from urllib.parse import urlparse, parse_qs
            u = urlparse(d)
            q = parse_qs(u.query)
            un = (q.get('u') or [''])[0].strip()
            if un and USERNAME_RE.match(un):
                return un[:32], (q.get('n') or [''])[0].strip()[:64]
        except Exception:
            pass
    return None, ''


def room_ok(params):
    if not ARGS.room:
        return True
    return (params.get('room') or [''])[0] == ARGS.room


def json_out(handler, code, obj):
    body = json.dumps(obj).encode('utf-8')
    handler.send_response(code)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    handler.send_header('Access-Control-Allow-Headers', 'Content-Type')
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    handler.wfile.write(body)


def session_row(token):
    row = db().execute('SELECT * FROM sessions WHERE token = ?', (token,)).fetchone()
    return row


def hunt_view(row):
    return {'on': bool(row['hunt_on']), 'targets': json.loads(row['targets']), 'won': json.loads(row['won'])}


def emit(receiver, ev_type, payload):
    with LOCK:
        db().execute('INSERT INTO events(receiver, type, payload, room, ts) VALUES (?,?,?,?,?)',
                     (receiver, ev_type, json.dumps(payload), ARGS.room, time.time()))
        db().commit()


def api_register(handler, params):
    try:
        body = json.loads(handler.body.decode('utf-8'))
    except Exception:
        return fail(400, 'bad json')
    username = (body.get('username') or '').strip()
    name = (body.get('name') or '').strip() or username
    if not USERNAME_RE.match(username) or not NAME_RE.match(name):
        return fail(400, 'bad username or name')
    if not room_ok(params):
        return fail(403, 'room code required or wrong')
    with LOCK:
        row = db().execute('SELECT * FROM sessions WHERE username = ?', (username,)).fetchone()
        if row is None:
            token = secrets.token_hex(16)
            db().execute('INSERT INTO sessions(token, username, name, created) VALUES (?,?,?,?)',
                         (token, username, name, time.time()))
            db().commit()
            row = db().execute('SELECT * FROM sessions WHERE token = ?', (token,)).fetchone()
    return 200, {'ok': True, 'token': row['token'], 'username': row['username'], 'name': row['name'], 'hunt': hunt_view(row)}


def api_state(handler, params):
    token = (params.get('token') or [''])[0]
    if not TOKEN_RE.match(token):
        return fail(400, 'bad token')
    with LOCK:
        row = session_row(token)
        if row is None:
            return fail(404, 'bad token')
        cursor = int((params.get('cursor') or ['0'])[0] or 0)
        evs = db().execute(
            'SELECT * FROM events WHERE receiver = ? AND id > ? AND ts > ? ORDER BY id LIMIT 100',
            (row['username'], cursor, time.time() - EVENT_TTL)).fetchall()
        db().execute('DELETE FROM events WHERE ts < ?', (time.time() - EVENT_TTL,))
        db().execute('DELETE FROM quiz WHERE ts < ?', (time.time() - QUIZ_TTL,))
        db().commit()
    events = [{'id': e['id'], 'type': e['type'], 'ts': e['ts'], **json.loads(e['payload'])} for e in evs]
    out = {'ok': True, 'username': row['username'], 'name': row['name'], 'hunt': hunt_view(row),
           'cursor': cursor, 'events': events}
    if ARGS.room:
        out['room'] = ARGS.room
    return 200, out


def api_scan(handler, params):
    try:
        body = json.loads(handler.body.decode('utf-8'))
    except Exception:
        return fail(400, 'bad json')
    token = (body.get('token') or '').strip()
    raw = (body.get('raw') or '').strip()[:128]
    if not TOKEN_RE.match(token):
        return fail(400, 'bad token')
    if not room_ok(params):
        return fail(403, 'room code required or wrong')
    owner, name = parse_payload(raw)
    if not owner:
        return fail(400, 'not a builder card')
    with LOCK:
        me = session_row(token)
        if me is None:
            return fail(404, 'bad token')
        if owner == me['username']:
            return fail(400, "that's your own card")
        owner_row = db().execute('SELECT * FROM sessions WHERE username = ?', (owner,)).fetchone()
        dup = db().execute(
            "SELECT payload FROM events WHERE receiver = ? AND type = 'connect' AND ts > ?",
            (me['username'], time.time() - EVENT_TTL)).fetchall()
        if not any(json.loads(e['payload']).get('owner') == owner for e in dup):
            emit(me['username'], 'connect', {'owner': owner, 'name': name})
        if owner_row is not None:
            emit(owner_row['username'], 'scanned', {'by': me['username'], 'byName': me['name'], 'owner': owner})
    return 200, {'ok': True, 'owner': owner, 'name': name, 'hunt': hunt_view(me)}


def api_hunt(handler, params, action):
    try:
        body = json.loads(handler.body.decode('utf-8'))
    except Exception:
        return fail(400, 'bad json')
    token = (body.get('token') or '').strip()
    if not TOKEN_RE.match(token):
        return fail(400, 'bad token')
    if not room_ok(params):
        return fail(403, 'room code required or wrong')
    with LOCK:
        row = session_row(token)
        if row is None:
            return fail(404, 'bad token')
        if action == 'start':
            target = body.get('target')
            if target and target in TRINKETS:
                targets = [target]
            else:
                targets = random.Random(secrets.token_hex(8)).sample(TRINKETS, 3)
            db().execute('UPDATE sessions SET hunt_on = 1, targets = ?, won = ? WHERE token = ?',
                         (json.dumps(targets), json.dumps([]), token))
        else:
            db().execute('UPDATE sessions SET hunt_on = 0, targets = ?, won = ? WHERE token = ?',
                         (json.dumps(TRINKETS[:3]), json.dumps([]), token))
        db().commit()
        row = session_row(token)
    return 200, {'ok': True, 'hunt': hunt_view(row)}


def api_quiz(handler, params):
    token = (params.get('token') or [''])[0]
    owner = (params.get('owner') or [''])[0]
    if not TOKEN_RE.match(token):
        return fail(400, 'bad token')
    if not room_ok(params):
        return fail(403, 'room code required or wrong')
    with LOCK:
        row = session_row(token)
        if row is None:
            return fail(404, 'bad token')
        hunt = hunt_view(row)
        if not hunt['on']:
            return fail(409, 'hunt is off for this builder')
        won = hunt['won']
        missing = [t for t in hunt['targets'] if t not in won]
        if not missing:
            return fail(409, 'all trinkets already collected')
        if owner == row['username']:
            return fail(400, "that's your own card")
        existing = db().execute(
            "SELECT * FROM quiz WHERE receiver = ? AND owner = ? AND status = 'pending' AND ends > ?",
            (row['username'], owner, time.time())).fetchone()
        if existing is not None:
            q = QUIZ[existing['qidx']]
            return 200, {'ok': True, 'qid': existing['qid'], 'endsAt': existing['ends'], 'category': q['c'],
                         'question': q['q'], 'options': q['o']}
        deck = QUIZ_RANDOM()
        qid = secrets.token_hex(8)
        ends = time.time() + QUIZ_SECONDS
        db().execute('INSERT INTO quiz(qid, receiver, owner, qidx, answer, ends, status, ts) VALUES (?,?,?,?,?,?,?,?)',
                     (qid, row['username'], owner, QUIZ.index(deck), deck['a'], ends, 'pending', time.time()))
        db().commit()
    return 200, {'ok': True, 'qid': qid, 'endsAt': ends, 'category': deck['c'],
                 'question': deck['q'], 'options': deck['o']}


def QUIZ_RANDOM():
    r = random.SystemRandom().randrange(len(QUIZ))
    return QUIZ[r]


def api_answer(handler, params):
    try:
        body = json.loads(handler.body.decode('utf-8'))
    except Exception:
        return fail(400, 'bad json')
    token = (body.get('token') or '').strip()
    qid = (body.get('qid') or '').strip()
    if not TOKEN_RE.match(token) or not re.match(r'^[0-9a-f]{8,32}$', qid):
        return fail(400, 'bad token or qid')
    choice = body.get('choice')
    if not isinstance(choice, int) or not 0 <= choice <= 3:
        return fail(400, 'bad choice')
    if not room_ok(params):
        return fail(403, 'room code required or wrong')
    now = time.time()
    with LOCK:
        me = session_row(token)
        if me is None:
            return fail(404, 'bad token')
        q = db().execute('SELECT * FROM quiz WHERE qid = ?', (qid,)).fetchone()
        if q is None or q['receiver'] != me['username']:
            return fail(404, 'no such quiz')
        if q['status'] != 'pending':
            db().execute("UPDATE quiz SET status = 'done' WHERE qid = ?", (qid,))
            db().commit()
            return 200, {'ok': True, 'result': 'late'}
        if now > q['ends'] + 1.0:
            db().execute("UPDATE quiz SET status = 'done' WHERE qid = ?", (qid,))
            db().commit()
            return 200, {'ok': True, 'result': 'late'}
        correct = choice == q['answer']
        db().execute("UPDATE quiz SET status = 'done' WHERE qid = ?", (qid,))
        trinket = None
        if correct:
            hunt = hunt_view(me)
            missing = [t for t in hunt['targets'] if t not in hunt['won']]
            if missing:
                trinket = random.choice(missing)
                won = list(hunt['won']) + [trinket]
                db().execute('UPDATE sessions SET won = ? WHERE token = ?', (json.dumps(won), token))
                emit(me['username'], 'trinket', {'owner': q['owner'], 'trinketId': trinket})
        db().commit()
    return 200, {'ok': True, 'result': 'correct' if correct else 'wrong', 'trinket': trinket}


def api_health(handler, params):
    return 200, {'ok': True, 'name': 'buildersbadge-hunt-hub', 'room': ARGS.room or '', 'trinkets': TRINKETS,
                 'quizSeconds': QUIZ_SECONDS}


API = {
    ('POST', 'register'): api_register,
    ('GET', 'state'): api_state,
    ('POST', 'scan'): api_scan,
    ('POST', 'hunt/start'): (lambda h, p: api_hunt(h, p, 'start')),
    ('POST', 'hunt/stop'): (lambda h, p: api_hunt(h, p, 'stop')),
    ('GET', 'quiz'): api_quiz,
    ('POST', 'answer'): api_answer,
    ('GET', 'health'): api_health,
}


class HubHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    body = b''

    def _body(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length:
            self.body = self.rfile.read(min(length, 16384))
        return self.body

    def route(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        path = u.path
        params = parse_qs(u.query)
        if path.startswith('/api/'):
            name = path[5:].strip('/')
            fn = API.get((self.command, name))
            self._body()
            if fn is None:
                code, obj = fail(404, 'no such api: ' + name)
            else:
                try:
                    code, obj = fn(self, params)
                except Exception as e:
                    code, obj = fail(500, 'server error: %s' % e)
            json_out(self, code, obj)
            return
        if self.command != 'GET':
            json_out(self, 405, {'ok': False, 'error': 'method'})
            return
        self.serve_static(path)

    def serve_static(self, path):
        base = ARGS.public
        rel = 'index.html' if path in ('/', '') else path.lstrip('/')
        full = os.path.normpath(os.path.join(base, rel))
        if not full.startswith(os.path.normpath(base)):
            self.send_error(404)
            return
        if not os.path.isfile(full):
            self.send_error(404)
            return
        mime = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
                '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.svg': 'image/svg+xml'}
        ext = os.path.splitext(full)[1].lower()
        with open(full, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', mime.get(ext, 'application/octet-stream'))
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.route()

    def do_POST(self):
        self.route()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Max-Age', '600')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def log_message(self, fmt, *args):
        pass


def main():
    global ARGS
    p = argparse.ArgumentParser(description='BuildersBadge hunt hub')
    p.add_argument('--port', type=int, default=8788)
    p.add_argument('--host', default='0.0.0.0')
    p.add_argument('--room', default=os.environ.get('BB_ROOM', ''),
                   help='optional access code; clients must pass ?room=CODE')
    p.add_argument('--public', default=os.path.join(HERE, 'public'))
    p.add_argument('--db', default=os.path.join(HERE, 'hunt_hub.db'))
    ARGS = p.parse_args()
    httpd = ThreadingHTTPServer((ARGS.host, ARGS.port), HubHandler)
    art = ('\n'
           '  \u2588\u2588\u2588\u2557 \u2588\u2588\u2557    \u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2557  \u2588\u2588\u2557\n'
           ' \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551    \u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551 \u2588\u2588\u2554\u255d\n'
           ' \u2588\u2588\u2557\u2550\u2550\u2550\u2588\u2588\u2551\u2588\u2588\u2551 \u2588\u2557 \u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2554\u255d\n'
           ' \u2588\u2588\u2551\u2550\u2550\u2588\u2588\u2551\u2588\u2588\u2551\u2588\u2588\u2588\u2557\u2588\u2588\u2551\u255a\u2550\u2550\u2550\u2588\u2588\u2588\u2588\u2588\u2588\u255d\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\n'
           ' \u2588\u2588\u2551  \u2588\u2588\u2551\u255a\u2588\u2588\u2588\u2554\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2557\n'
           ' \u255a\u2550\u255d  \u255a\u2550\u255d \u255a\u2550\u2550\u255d\u255a\u2550\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d  HUNT HUB\n')
    try:
        sys.stdout.buffer.write(art.encode('utf-8'))
        sys.stdout.flush()
    except Exception:
        print('\n  AWS STUDENT BUILDERS - HUNT HUB\n')
    print('  hub UI:      http://localhost:%d/' % ARGS.port)
    print('  api health:  http://localhost:%d/api/health' % ARGS.port)
    print('  room code:   %s' % (ARGS.room or '(open — set --room to gate writes)'))
    print('  db:          %s' % ARGS.db)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
