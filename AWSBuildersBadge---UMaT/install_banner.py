"""BuildsBadge server banner - single-file installer + runtime banner module.

Run ONCE from the project folder:

    python install_banner.py

installs itself as ``buildersbadge_serve`` (plus a ``.pth`` startup trigger)
into this Python's site-packages. Afterwards, any plain

    python -m http.server

run inside a BuildersBadge folder prints the AWS STUDENT BADGE banner:
block art, this-computer URL, LAN URL for phones, and a scannable QR code.
No changes to the served site are required.

Options:
    python install_banner.py --user      install into the user-site folder
    python install_banner.py --remove    uninstall both files

Notes:
    QR art needs the `qrcode` package:  pip install qrcode
    (URLs and block art work fine without it. `print_ascii` needs no Pillow.)
    Windows Firewall may prompt once when a phone first opens the LAN URL.
    Set BUILDERBADGE_NOBANNER=1 to silence the banner without uninstalling.
"""
import os
import sys

_IS_MAIN = __name__ == '__main__'

_FONT = {
    'A': ['.███.', '█...█', '█████'],
    'W': ['█...█', '█.█.█', '.███.'],
    'S': ['.████', '█████', '████.'],
    'T': ['█████', '..█..', '..█..'],
    'U': ['█...█', '█...█', '.███.'],
    'D': ['████.', '█...█', '████.'],
    'E': ['█████', '██...', '█████'],
    'N': ['█...█', '██.██', '█...█'],
    'B': ['████.', '█.██.', '████.'],
    'G': ['█████', '█.███', '█████'],
    ' ': ['.....', '.....', '.....'],
}


def _lan_ip():
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _qr(url):
    try:
        import qrcode
    except Exception:
        return None
    try:
        import contextlib
        import io

        qr = qrcode.QRCode(border=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
        qr.add_data(url)
        qr.make(fit=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            qr.print_ascii(invert=True)
        return buf.getvalue().rstrip('\n')
    except Exception:
        return None


def _art(text):
    glyphs = [_FONT.get(ch, _FONT[' ']) for ch in text]
    return [''.join(g[r].replace('.', ' ') for g in glyphs) for r in range(3)]


def _out(s):
    try:
        sys.stdout.buffer.write(s.encode('utf-8', 'replace'))
        sys.stdout.buffer.write(b'\n')
        sys.stdout.buffer.flush()
    except Exception:
        try:
            sys.stdout.write(s + '\n')
        except Exception:
            pass


def _banner(host, port):
    green, dim, bold, res = '\033[92m', '\033[90m', '\033[1m', '\033[0m'
    if os.name == 'nt':
        try:
            import ctypes

            k = ctypes.windll.kernel32
            m = ctypes.c_uint32()
            h = k.GetStdHandle(-11)
            k.GetConsoleMode(h, ctypes.byref(m))
            k.SetConsoleMode(h, m.value | 4)
        except Exception:
            pass

    def fmt(ip):
        h = f'[{ip}]' if ':' in ip else ip
        return f'http://{h}:{port}'

    wild = host in ('0.0.0.0', '::')
    loopback = host in ('127.0.0.1', '::1')
    lan = _lan_ip()
    print()
    for line in _art('AWS STUDENT BADGE'):
        _out(green + line + res)
    print()
    qr_url = None
    if wild:
        _out(dim + 'this computer          ' + res + fmt('localhost'))
        if lan:
            qr_url = fmt(lan)
            _out(bold + 'phone (same Wi-Fi)     ' + res + green + qr_url + res)
        else:
            _out(dim + 'no network interface detected - phones cannot reach this server' + res)
    elif loopback:
        _out(dim + 'this computer          ' + res + fmt('localhost'))
        _out(dim + 'bound to loopback - phones cannot reach a --bind 127.0.0.1 server; re-run without --bind or use --bind <LAN IP>' + res)
    else:
        _out(dim + 'this computer          ' + res + fmt(host))
        if lan and lan != host:
            qr_url = fmt(lan)
            _out(bold + 'phone (same Wi-Fi)     ' + res + green + qr_url + res)
        else:
            _out(dim + 'no separate LAN IP detected - phones may not reach this server' + res)
    qr = _qr(qr_url) if qr_url else None
    if qr:
        print()
        for line in qr.split('\n'):
            _out(line)
    else:
        print()
        _out(dim + 'QR disabled - one-time: pip install qrcode' + res)
    _out(dim + 'phone must be on the same Wi-Fi · Ctrl+C stops the server' + res)
    _out(dim + 'silence banner: set BUILDERBADGE_NOBANNER=1' + res)
    print()
    sys.stdout.flush()


def _server_dir():
    a = sys.argv
    d = None
    for i, x in enumerate(a):
        if x in ('-d', '--directory') and i + 1 < len(a):
            d = a[i + 1]
        elif x.startswith('--directory='):
            d = x.split('=', 1)[1]
    if d is None:
        d = os.getcwd()
    return d if os.path.isfile(os.path.join(d, 'config.json')) and os.path.isfile(os.path.join(d, 'index.html')) else None


def _activate():
    if sys.argv[:1] != ['-m']:
        return
    if _server_dir() is None:
        return
    try:
        import socketserver
    except Exception:
        return
    if getattr(socketserver.TCPServer, '_bb_badge', False):
        return
    bound = socketserver.TCPServer.server_bind
    state = {'done': False}

    def bind(self):
        bound(self)
        if state['done']:
            return
        state['done'] = True
        try:
            ms = sys.modules.get('__main__')
            spec = getattr(ms, '__spec__', None)
            if spec and spec.name == 'http.server':
                addr = self.server_address
                _banner(addr[0], addr[1])
        except Exception:
            pass

    socketserver.TCPServer.server_bind = bind
    socketserver.TCPServer._bb_badge = True


def _target(scheme=None):
    import sysconfig

    return sysconfig.get_path('purelib') if scheme is None else sysconfig.get_path(scheme)


def _install(user):
    import shutil

    src = os.path.abspath(__file__)
    tgt = _target('nt_user' if user and os.name == 'nt' else ('posix_user' if user and os.name != 'nt' else None))
    if not tgt:
        print('could not resolve the target site-packages folder')
        return 1
    mod = os.path.join(tgt, 'buildersbadge_serve.py')
    pth = os.path.join(tgt, 'buildersbadge_serve.pth')
    try:
        shutil.copyfile(src, mod)
    except PermissionError:
        print('permission denied for ' + tgt)
        print('try:  python install_banner.py --user    (installs into your user site)')
        return 1
    with open(pth, 'w', encoding='utf-8') as f:
        f.write('import buildersbadge_serve\n')
    print('installed:')
    print('  ' + mod)
    print('  ' + pth)
    print()
    print('done. from any BuildersBadge folder run:  python -m http.server')
    print('optional QR art:  pip install qrcode')
    print('silence or uninstall:  python install_banner.py --remove')
    return 0


def _remove():
    out = False
    try:
        tgt = _target()
        mod = os.path.join(tgt, 'buildersbadge_serve.py')
        pth = os.path.join(tgt, 'buildersbadge_serve.pth')
        for f in (mod, pth):
            if os.path.isfile(f):
                os.remove(f)
                print('removed ' + f)
                out = True
    except Exception as e:
        print('remove failed: ' + e)
    if not out:
        print('nothing to remove')
    return 0


if _IS_MAIN:
    sys.exit(_remove() if '--remove' in sys.argv[1:] else _install('--user' in sys.argv[1:]))
else:
    if os.environ.get('BUILDERBADGE_NOBANNER') != '1':
        try:
            _activate()
        except Exception:
            pass
