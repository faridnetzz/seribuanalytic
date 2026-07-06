"""Proxy HLS internal — dekripsi AES-128 stream seribuwajah agar bisa dibaca OpenCV.

Kunci: endpoint key mengirim 32-char HEX string; AES key sebenarnya = 16 KARAKTER
PERTAMA sebagai byte ASCII (BUKAN hex-decode). Tanpa ini ffmpeg gagal decrypt.
Jalan di dalam container engine pada port lokal (config.HLS_PROXY_PORT).
"""
import http.cookiejar
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config

log = logging.getLogger("engine.hlsproxy")
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://seribuwajah.bandarlampungkota.go.id/",
}

# Cache playlist per-kamera (TTL pendek): ffmpeg me-refresh playlist live tiap
# ~target-duration; 5 kamera × refresh sering = banjir request ke upstream ->
# upstream lambat/limit -> playlist stall -> grabber kehabisan frame -> video freeze.
# Cache 1.5s meredam tanpa bikin playlist basi (segmen baru muncul tiap beberapa detik).
_PLAYLIST_TTL = 1.5
_pl_cache = {}            # cam -> (ts, text)
_pl_lock = threading.Lock()

# --- Sesi embed (skema newseribuwajah, auth COOKIE) ---
_embed_lock = threading.Lock()
_embed_sess = {}          # cam -> {opener, variant, hdr, ts}
_embed_pl_cache = {}      # cam -> (ts, text, base)


def _fetch(url, timeout=10):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _build_embed(cam):
    """Bangun sesi ber-cookie + resolve URL playlist VARIANT (media) kamera embed.
    Alur auth: GET api embed (set cookie stream_token + streamUrl master) -> GET master
    (redirect cookieCheck -> set hlsSession) -> ambil baris variant pertama."""
    info = config.LIVE_EMBED_CAMERAS[cam]
    ref = info["referer"]
    hdr = {"User-Agent": "Mozilla/5.0", "Referer": ref, "Origin": ref.rstrip("/")}
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    # 1) api embed -> cookie stream_token + streamUrl (master m3u8)
    with opener.open(urllib.request.Request(info["api"], headers=hdr), timeout=10) as r:
        meta = json.loads(r.read().decode("utf-8", "replace"))
    master = meta["streamUrl"]
    # 2) master (ikuti redirect cookieCheck -> hlsSession) -> pilih variant pertama
    with opener.open(urllib.request.Request(master, headers=hdr), timeout=10) as r:
        master_url, text = r.geturl(), r.read().decode("utf-8", "replace")
    variant = next((urllib.parse.urljoin(master_url, ln) for ln in text.splitlines()
                    if ln and not ln.startswith("#")), master)
    log.info("[%s] sesi embed siap: %s", cam, meta.get("name", cam))
    return {"opener": opener, "variant": variant, "hdr": hdr, "ts": time.time()}


def _embed_session(cam, force=False):
    with _embed_lock:
        s = _embed_sess.get(cam)
        if s and not force and time.time() - s["ts"] < config.EMBED_SESSION_TTL:
            return s
    s = _build_embed(cam)                     # network di luar lock
    with _embed_lock:
        _embed_sess[cam] = s
    return s


def _embed_fetch(cam, url, timeout=15):
    """Fetch URL pakai sesi cookie kamera. Re-auth sekali bila 401/403 (token expired)."""
    s = _embed_session(cam)
    for attempt in (0, 1):
        try:
            with s["opener"].open(urllib.request.Request(url, headers=s["hdr"]), timeout=timeout) as r:
                return r.read(), r.geturl()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and attempt == 0:
                s = _embed_session(cam, force=True)   # token kadaluarsa -> bangun ulang sesi
                continue
            raise


def _fetch_playlist_text(cam, manifest):
    now = time.time()
    with _pl_lock:
        hit = _pl_cache.get(cam)
        if hit and now - hit[0] < _PLAYLIST_TTL:
            return hit[1]
    text = _fetch(manifest).decode("utf-8", "replace")
    with _pl_lock:
        _pl_cache[cam] = (now, text)
    return text


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            path = urllib.parse.urlparse(self.path).path
            if path.startswith("/playlist/"):
                self._playlist(path.split("/", 2)[2])
            elif path == "/key":
                self._key()
            elif path == "/seg":
                self._seg()
            else:
                self.send_error(404)
        except Exception as e:
            self.send_error(502, str(e))

    def _playlist(self, cam):
        if cam in config.LIVE_EMBED_CAMERAS:
            self._playlist_embed(cam)
            return
        manifest = config.LIVE_CAMERAS.get(cam)
        if not manifest:
            self.send_error(404, "kamera tak dikenal: %s" % cam)
            return
        text = _fetch_playlist_text(cam, manifest)
        out = []
        for line in text.splitlines():
            if line.startswith("#EXT-X-KEY"):
                line = re.sub(r'URI="[^"]*"',
                              'URI="http://127.0.0.1:%d/key"' % config.HLS_PROXY_PORT, line)
            elif line and not line.startswith("#"):
                absu = urllib.parse.urljoin(manifest, line)
                line = "/seg?u=" + urllib.parse.quote(absu, safe="")
            out.append(line)
        self._send(("\n".join(out) + "\n").encode(), "application/vnd.apple.mpegurl")

    def _playlist_embed(self, cam):
        """Playlist VARIANT (media) kamera embed: segmen .ts POLOS (tanpa AES) ->
        rewrite tiap segmen ke /seg (dibawa cookie sesi). Cache pendek seperti biasa."""
        now = time.time()
        with _pl_lock:
            hit = _embed_pl_cache.get(cam)
        if hit and now - hit[0] < _PLAYLIST_TTL:
            text, base = hit[1], hit[2]
        else:
            s = _embed_session(cam)
            body, base = _embed_fetch(cam, s["variant"])
            text = body.decode("utf-8", "replace")
            with _pl_lock:
                _embed_pl_cache[cam] = (now, text, base)
        out = []
        for line in text.splitlines():
            if line and not line.startswith("#"):
                absu = urllib.parse.urljoin(base, line)
                line = "/seg?cam=%s&u=%s" % (urllib.parse.quote(cam),
                                             urllib.parse.quote(absu, safe=""))
            out.append(line)
        self._send(("\n".join(out) + "\n").encode(), "application/vnd.apple.mpegurl")

    def _key(self):
        raw = _fetch(config.LIVE_HLS_KEY_URL).decode().strip()
        self._send(raw[:16].encode("ascii"), "application/octet-stream")  # 16 char pertama = key

    def _seg(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        cam = qs.get("cam", [None])[0]
        if cam and cam in config.LIVE_EMBED_CAMERAS:
            body, _ = _embed_fetch(cam, qs["u"][0])       # segmen dibawa cookie sesi
            self._send(body, "video/mp2t")
        else:
            self._send(_fetch(qs["u"][0], timeout=15), "video/mp2t")


def start(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True, name="hlsproxy").start()
    log.info("HLS proxy internal aktif di :%d", port)
