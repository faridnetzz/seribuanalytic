"""Tes stream Jembatan Milenial 1 (CAM-05, skema embed newseribuwajah) +
deteksi orang + Face Recognition. Aplikasi Python standalone (di luar engine).

TEMUAN PENTING (dari benchmark): stream HLS ini dikirim per-segmen ~2 detik, jadi
ke pembaca DATANG MELEDAK lalu STALL sampai ~3 detik (gejala "freeze lalu ngejar
frame"). Pembaca MENTAH (1 loop cap.read()+tampil) JUSTRU paling parah burst/stall-
nya. Kunci kemulusan = pisahkan BACA dari TAMPIL + buffer playout cukup DALAM untuk
menyerap stall, lalu kuras buffer pada laju STABIL.

Mode (untuk membandingkan):
    python cam05_stream_test.py              # mode SMOOTH (default): thread baca + buffer playout
    python cam05_stream_test.py --raw        # mode MENTAH: 1 loop baca+tampil (lihat freeze/ngejar)
    python cam05_stream_test.py --no-fr      # tanpa Face Recognition
Opsi: --play-fps 25  --prebuffer-s 3.0  --buffer-s 10  --embed-id 22

Tekan 'q' untuk keluar.
"""
import argparse
import http.cookiejar
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

EMBED_BASE = "https://newseribuwajah.bandarlampungkota.go.id"
REFERER = EMBED_BASE + "/"
PERSON_MODEL = "engine/models/person.pt"
FACE_ROOT = "engine/models/insightface"          # berisi models/antelopev2/
FACE_NAME = "antelopev2"
PROXY_PORT = 8799


# ─── Sesi embed (auth cookie) + proxy lokal ──────────────────────────────────
class EmbedSession:
    def __init__(self, embed_id):
        self.api = f"{EMBED_BASE}/api/cctvs/public/embed/{embed_id}"
        self.hdr = {"User-Agent": "Mozilla/5.0", "Referer": REFERER, "Origin": EMBED_BASE}
        self.opener = self.variant = self.name = None
        self.build()

    def build(self):
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        with opener.open(urllib.request.Request(self.api, headers=self.hdr), timeout=10) as r:
            meta = json.loads(r.read().decode("utf-8", "replace"))
        master = meta["streamUrl"]
        self.name = meta.get("name", "")
        with opener.open(urllib.request.Request(master, headers=self.hdr), timeout=10) as r:
            murl, text = r.geturl(), r.read().decode("utf-8", "replace")
        self.variant = next((urllib.parse.urljoin(murl, l) for l in text.splitlines()
                             if l and not l.startswith("#")), master)
        self.opener = opener
        print(f"[auth] sesi siap: {self.name} | {self.variant}")

    def fetch(self, url, timeout=15):
        for attempt in (0, 1):
            try:
                with self.opener.open(urllib.request.Request(url, headers=self.hdr), timeout=timeout) as r:
                    return r.read(), r.geturl()
            except urllib.error.HTTPError as e:
                if e.code in (401, 403) and attempt == 0:
                    print(f"[auth] {e.code} -> re-auth"); self.build(); continue
                raise


_sess = None
_pl = {"ts": 0.0, "text": "", "base": ""}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, b, c):
        self.send_response(200); self.send_header("Content-Type", c)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        try:
            p = urllib.parse.urlparse(self.path)
            if p.path == "/playlist":
                now = time.time()
                if now - _pl["ts"] < 1.0:
                    text, base = _pl["text"], _pl["base"]
                else:
                    body, base = _sess.fetch(_sess.variant)
                    text = body.decode("utf-8", "replace"); _pl.update(ts=now, text=text, base=base)
                out = []
                for l in text.splitlines():
                    if l and not l.startswith("#"):
                        l = "/seg?u=" + urllib.parse.quote(urllib.parse.urljoin(base, l), safe="")
                    out.append(l)
                self._send(("\n".join(out) + "\n").encode(), "application/vnd.apple.mpegurl")
            elif p.path == "/seg":
                u = urllib.parse.parse_qs(p.query)["u"][0]
                body, _ = _sess.fetch(u); self._send(body, "video/mp2t")
            else:
                self.send_error(404)
        except Exception as e:
            self.send_error(502, str(e))


def start_proxy():
    srv = ThreadingHTTPServer(("127.0.0.1", PROXY_PORT), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"[proxy] http://127.0.0.1:{PROXY_PORT}/playlist")


# ─── Thread pembaca (BACA terpisah dari TAMPIL) ──────────────────────────────
class Reader:
    """Baca stream di thread sendiri secepat frame datang (telan burst), simpan ke
    buffer playout FIFO. Display menguras buffer pada laju STABIL -> mulus."""
    def __init__(self, url, buffer_max):
        self.url = url
        self.buf = deque(maxlen=buffer_max)
        self.lock = threading.Lock()
        self.src_fps = 0.0
        self.stalls = 0
        self.alive = True

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start(); return self

    def _open(self):
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        try: cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception: pass
        return cap

    def _loop(self):
        cap = self._open(); tp = None; fails = 0
        while self.alive:
            ok, fr = cap.read(); now = time.time()
            if not ok:
                fails += 1
                if fails > 50:
                    cap.release(); cap = self._open(); fails = 0
                time.sleep(0.02); continue
            fails = 0
            if tp is not None:
                dt = now - tp
                if dt > 0.5: self.stalls += 1
                inst = 1.0 / dt if dt > 0 else 0.0
                # EMA hanya pada dt 'realtime' (>5ms) -> abaikan burst utk estimasi fps sumber
                if dt > 0.005:
                    self.src_fps = inst if self.src_fps == 0 else 0.9 * self.src_fps + 0.1 * inst
            tp = now
            with self.lock:
                self.buf.append(fr)

    def pop(self):
        with self.lock:
            return self.buf.popleft() if self.buf else None

    def depth(self):
        with self.lock:
            return len(self.buf)


# ─── Inferensi ───────────────────────────────────────────────────────────────
def annotate(frame, model, face_app, i, fr_every, faces, imgsz):
    res = model.predict(frame, classes=[0], conf=0.35, imgsz=imgsz,
                        device=0, half=True, verbose=False)[0]
    n = 0
    if res.boxes is not None:
        for b in res.boxes.xyxy.cpu().numpy().astype(int):
            cv2.rectangle(frame, (b[0], b[1]), (b[2], b[3]), (80, 220, 120), 2); n += 1
    if face_app is not None and i % fr_every == 0:
        faces[:] = face_app.get(frame)
    for f in faces:
        fb = f.bbox.astype(int)
        cv2.rectangle(frame, (fb[0], fb[1]), (fb[2], fb[3]), (60, 160, 255), 2)
    return n


def hud(frame, lines, warn=False):
    color = (0, 0, 255) if warn else (0, 220, 0)
    for k, line in enumerate(lines):
        cv2.putText(frame, line, (12, 28 + k * 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)


# ─── Main ────────────────────────────────────────────────────────────────────
def main():
    global _sess
    ap = argparse.ArgumentParser()
    ap.add_argument("--embed-id", default="22")
    ap.add_argument("--raw", action="store_true", help="mode MENTAH (1 loop, tanpa buffer) -> lihat freeze/ngejar")
    ap.add_argument("--no-fr", action="store_true")
    ap.add_argument("--fr-every", type=int, default=15)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--play-fps", type=float, default=25.0)
    ap.add_argument("--prebuffer-s", type=float, default=3.0, help="isi buffer dulu (serap stall)")
    ap.add_argument("--buffer-s", type=float, default=10.0)
    args = ap.parse_args()

    _sess = EmbedSession(args.embed_id); start_proxy()
    url = f"http://127.0.0.1:{PROXY_PORT}/playlist"

    from ultralytics import YOLO
    print("[model] YOLO person..."); model = YOLO(PERSON_MODEL)
    face_app = None
    if not args.no_fr:
        try:
            from insightface.app import FaceAnalysis
            print("[model] insightface antelopev2...")
            face_app = FaceAnalysis(name=FACE_NAME, root=FACE_ROOT,
                                    providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
            face_app.prepare(ctx_id=0, det_size=(384, 384))
        except Exception as e:
            print(f"[model] FR gagal ({e}) -> tanpa FR"); face_app = None

    win = f"CAM-05 Jembatan Milenial 1 — {'MENTAH' if args.raw else 'SMOOTH (buffered)'}"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL); cv2.resizeWindow(win, 1280, 720)
    faces = []; i = 0

    if args.raw:
        # ── MODE MENTAH: 1 loop baca+infer+tampil. Akan terlihat burst/freeze. ──
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        try: cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception: pass
        print("[play] MODE MENTAH — tekan 'q'")
        tp = time.time(); fps = 0.0
        while True:
            ok, fr = cap.read(); now = time.time()
            if not ok: time.sleep(0.02); continue
            i += 1; dt = now - tp; tp = now
            fps = (1/dt if dt > 0 else 0) if fps == 0 else 0.9*fps + 0.1*(1/dt if dt > 0 else 0)
            n = annotate(fr, model, face_app, i, args.fr_every, faces, args.imgsz)
            hud(fr, [f"MENTAH  FPS {fps:4.1f}  dt {dt*1000:5.0f}ms", f"orang {n}  wajah {len(faces)}"],
                warn=dt > 0.5)
            cv2.imshow(win, fr)
            if cv2.waitKey(1) & 0xFF == ord("q"): break
        cap.release(); cv2.destroyAllWindows(); return

    # ── MODE SMOOTH: thread baca + buffer playout, kuras pada laju stabil. ──
    rd = Reader(url, buffer_max=int(args.buffer_s * max(args.play_fps, 25))).start()
    need = int(args.prebuffer_s * args.play_fps)
    print(f"[buffer] prebuffer {need} frame (~{args.prebuffer_s:.0f}s) untuk serap stall...")
    while rd.depth() < need:
        time.sleep(0.05)
    print("[play] MODE SMOOTH — tekan 'q'")
    interval = 1.0 / args.play_fps
    nxt = time.time(); last = None; play_fps = 0.0; tp = time.time()
    while True:
        fr = rd.pop()
        if fr is not None: last = fr
        if last is not None:
            img = last.copy(); i += 1
            now = time.time(); dt = now - tp; tp = now
            play_fps = (1/dt if dt > 0 else 0) if play_fps == 0 else 0.9*play_fps + 0.1*(1/dt if dt > 0 else 0)
            n = annotate(img, model, face_app, i, args.fr_every, faces, args.imgsz)
            depth = rd.depth()
            hud(img, [f"SMOOTH play {play_fps:4.1f}fps  sumber {rd.src_fps:4.1f}fps  buffer {depth:3d}f",
                      f"orang {n}  wajah {len(faces)}  stall sumber: {rd.stalls}"],
                warn=depth == 0)
            if depth == 0:
                cv2.putText(img, "BUFFER KOSONG (stall > prebuffer)", (12, 92),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            cv2.imshow(win, img)
        if cv2.waitKey(1) & 0xFF == ord("q"): break
        nxt += interval
        d = nxt - time.time()
        if d > 0: time.sleep(d)
        else: nxt = time.time()
    rd.alive = False; cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
