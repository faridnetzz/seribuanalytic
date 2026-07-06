"""
Proxy HLS lokal untuk CCTV seribuwajah Bandar Lampung.

Masalah: endpoint key mengirim HEX-STRING (33 byte ASCII), bukan 16 byte biner
seperti yang diharapkan ffmpeg. Proxy ini:
  /playlist        -> ambil manifest asli, rewrite URI key -> /key, segmen -> /seg
  /key             -> ambil key asli, hex-decode jadi 16 byte biner
  /seg?u=<abs_url> -> teruskan segmen .ts (header auth ditambahkan di sini)

Jalankan:  python proxy.py
Lalu arahkan ffmpeg/OpenCV ke:  http://127.0.0.1:8787/playlist
"""
import re
import urllib.request
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---- konfigurasi ----
MANIFEST_URL = "https://sliceseribuwajah.bandarlampungkota.go.id/resource/stream?key=1775807311736"
KEY_URL      = "https://sliceseribuwajah.bandarlampungkota.go.id/encryption.key"
PORT         = 8787
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://seribuwajah.bandarlampungkota.go.id/",
}
# ----------------------


def fetch(url, timeout=10):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # diam; ganti ke print(a) kalau mau debug

    def _send(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            path = urllib.parse.urlparse(self.path).path
            if path == "/playlist":
                self._playlist()
            elif path == "/key":
                self._key()
            elif path == "/seg":
                self._seg()
            else:
                self.send_error(404)
        except Exception as e:
            self.send_error(502, str(e))

    def _playlist(self):
        text = fetch(MANIFEST_URL).decode("utf-8", "replace")
        out = []
        for line in text.splitlines():
            if line.startswith("#EXT-X-KEY"):
                # arahkan key ke proxy lokal (yang sudah hex-decode)
                line = re.sub(r'URI="[^"]*"', 'URI="http://127.0.0.1:%d/key"' % PORT, line)
            elif line and not line.startswith("#"):
                # segmen: resolve jadi absolut, lalu proxy
                absu = urllib.parse.urljoin(MANIFEST_URL, line)
                line = "/seg?u=" + urllib.parse.quote(absu, safe="")
            out.append(line)
        body = ("\n".join(out) + "\n").encode()
        self._send(body, "application/vnd.apple.mpegurl")

    def _key(self):
        # Endpoint mengirim 32-char hex string. TERNYATA player situs memakai
        # 16 KARAKTER PERTAMA sebagai byte ASCII mentah (BUKAN hasil hex-decode).
        # IV dibiarkan kosong di manifest -> ffmpeg pakai media-sequence otomatis.
        raw = fetch(KEY_URL).decode().strip()
        key = raw[:16].encode("ascii")
        assert len(key) == 16, "key bukan 16 byte: %d" % len(key)
        self._send(key, "application/octet-stream")

    def _seg(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        url = qs["u"][0]
        self._send(fetch(url, timeout=15), "video/mp2t")


if __name__ == "__main__":
    print("Proxy HLS jalan di  http://127.0.0.1:%d/playlist" % PORT)
    print("Manifest sumber  :", MANIFEST_URL)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
