"""Server MJPEG ringan — menyajikan frame teranotasi per kamera ke dashboard.

Sumber frame:
- publish_annotated(): dipakai FrameWorker (gambar kotak dari bbox ternormalisasi).
- publish_frame():     dipakai live_stream (frame sudah teranotasi via res.plot()).

MJPEG mengirim frame begitu ada versi baru (mendekati realtime), bukan poll lambat.
Endpoint (CORS terbuka, aman di-embed <img>):
  GET /stream/<cam>    -> multipart MJPEG
  GET /snapshot/<cam>  -> 1 frame JPEG
  GET /cameras         -> daftar kamera (JSON)
"""
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import cv2

from . import roi_store
from . import enroll
from . import snapshots
from . import config
from urllib.parse import parse_qs

log = logging.getLogger("engine.stream")

_frames = {}      # cam_id -> bytes JPEG terbaru
_versions = {}    # cam_id -> int (naik tiap frame baru)
_lock = threading.Lock()

# Placeholder "sumber offline" — ditampilkan saat kamera BELUM pernah mengirim frame
# (mis. server CCTV upstream down / stream putus di startup). Tanpa ini, <img> ke
# /stream menggantung hitam tanpa penjelasan. Frame di-regenerate berkala (jam berjalan)
# supaya jelas ini heartbeat LIVE, bukan gambar error yang beku.
import numpy as np


def _placeholder_jpeg(cam_id):
    W = 640
    img = np.full((360, W, 3), 18, dtype=np.uint8)   # abu gelap

    def _center(text, y, scale, color, thick):
        (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
        cv2.putText(img, text, ((W - tw) // 2, y), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, color, thick, cv2.LINE_AA)
        return tw

    tw = _center("SUMBER CCTV OFFLINE", 158, 0.8, (210, 210, 210), 2)
    cv2.circle(img, ((W - tw) // 2 - 22, 151), 8, (60, 60, 240), -1)  # titik merah "offline"
    _center(str(cam_id), 195, 0.7, (120, 120, 120), 2)
    _center("Menunggu koneksi ke server CCTV...", 250, 0.55, (150, 150, 150), 1)
    _center(time.strftime("%H:%M:%S"), 300, 0.6, (90, 90, 90), 1)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return buf.tobytes() if ok else b""


def _store(cam_id, jpg_bytes):
    with _lock:
        _frames[cam_id] = jpg_bytes
        _versions[cam_id] = _versions.get(cam_id, 0) + 1


def publish_frame(cam_id, img):
    """Simpan frame BGR (sudah teranotasi) sebagai JPEG terbaru kamera.
    Downscale ke STREAM_MAX_W -> encode jauh lebih ringan (CPU/GIL) & bandwidth kecil."""
    if config.STREAM_MAX_W and img.shape[1] > config.STREAM_MAX_W:
        s = config.STREAM_MAX_W / float(img.shape[1])
        img = cv2.resize(img, (config.STREAM_MAX_W, int(img.shape[0] * s)),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, config.STREAM_JPEG_Q])
    if ok:
        _store(cam_id, buf.tobytes())


def publish_annotated(cam_id, frame, results):
    """Gambar kotak deteksi (dari bbox ternormalisasi) lalu simpan. results = list (data, conf)."""
    img = frame.copy()
    h, w = img.shape[:2]
    for data, conf in results:
        bb = data.get("bbox") if isinstance(data, dict) else None
        if not bb:
            continue
        x, y = int(bb["x"] * w), int(bb["y"] * h)
        bw, bh = int(bb["w"] * w), int(bb["h"] * h)
        cv2.rectangle(img, (x, y), (x + bw, y + bh), (40, 200, 255), 2)
        cv2.putText(img, f"sampah {conf:.2f}", (x, max(y - 6, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 200, 255), 2)
    if results:
        cv2.putText(img, f"SAMPAH: {len(results)}", (12, h - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    publish_frame(cam_id, img)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _head(self, ctype, length=None):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _read_json(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def _json_ok(self, obj):
        body = json.dumps(obj).encode()
        self._head("application/json", len(body))
        self.wfile.write(body)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path.startswith("/roi/"):
                cam = path.split("/", 2)[2]
                b = self._read_json()
                roi_store.set_roi(cam, b.get("polygon", []), b.get("dwellSeconds"))
                self._json_ok({"ok": True})
                return
            if path == "/enroll/capture":
                b = self._read_json()
                self._json_ok(enroll.capture(b.get("name"), b.get("cam")))
                return
            if path == "/enroll/finish":
                self._json_ok(enroll.finish())
                return
            if path == "/enroll-from-snapshot":
                b = self._read_json()
                res = snapshots.enroll_from(b.get("id"), b.get("name"))
                if res.get("ok"):
                    enroll.finish()        # rebuild galeri -> langsung dikenali
                self._json_ok(res)
                return
            if path == "/snapshot-delete":
                self._json_ok(snapshots.delete(self._read_json().get("id")))
                return
            if path == "/park-snapshot-delete":
                self._json_ok(snapshots.delete_parking(self._read_json().get("id")))
                return
            if path == "/park-snapshots-clear":
                self._json_ok(snapshots.clear_parking())
                return
            if path == "/waste-snapshot-delete":
                self._json_ok(snapshots.delete_waste(self._read_json().get("id")))
                return
            if path == "/waste-snapshots-clear":
                self._json_ok(snapshots.clear_waste())
                return
        except Exception as e:
            self.send_error(400, str(e))
            return
        self.send_error(404)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/enroll/list":
            self._json_ok({"enrolled": enroll.list_enrolled()})
            return
        if path == "/snapshots":
            q = parse_qs(parsed.query)
            cam = q.get("cam", [None])[0]
            identity = q.get("identity", [None])[0]
            items = snapshots.list_items(
                cam=cam, identity=identity,
                limit=int(q.get("limit", ["240"])[0]),
                offset=int(q.get("offset", ["0"])[0]))
            self._json_ok({"items": items, "total": snapshots.count_items(cam, identity)})
            return
        if path == "/trajectory":
            q = parse_qs(parsed.query)
            gid = q.get("gid", [None])[0]
            self._json_ok({"sightings": snapshots.list_sightings(gid) if gid else []})
            return
        if path == "/park-snapshots":
            q = parse_qs(parsed.query)
            items = snapshots.list_parking(
                cam=(q.get("cam", [None])[0]),
                limit=int(q.get("limit", ["120"])[0]))
            self._json_ok({"items": items})
            return
        if path == "/waste-snapshots":
            q = parse_qs(parsed.query)
            items = snapshots.list_waste(
                cam=(q.get("cam", [None])[0]),
                limit=int(q.get("limit", ["120"])[0]))
            self._json_ok({"items": items})
            return
        if path.startswith("/snap-img/"):
            sid = path.split("/", 2)[2]
            kind = parse_qs(parsed.query).get("kind", ["body"])[0]
            p = snapshots.img_path(sid, kind)
            if not p:
                self.send_error(404)
                return
            with open(p, "rb") as f:
                data = f.read()
            self._head("image/jpeg", len(data))
            self.wfile.write(data)
            return
        if path.startswith("/roi/"):
            cam = path.split("/", 2)[2]
            body = json.dumps({
                "polygon": roi_store.get(cam) or [],
                "dwellSeconds": roi_store.get_dwell(cam) or config.PARK_DWELL_S,
            }).encode()
            self._head("application/json", len(body))
            self.wfile.write(body)
            return
        if path == "/cameras":
            with _lock:
                cams = sorted(_frames.keys())
            body = json.dumps({"cameras": cams}).encode()
            self._head("application/json", len(body))
            self.wfile.write(body)
            return
        if path.startswith("/snapshot/"):
            cam = path.split("/", 2)[2]
            with _lock:
                jpg = _frames.get(cam)
            if not jpg:
                jpg = _placeholder_jpeg(cam)   # sumber belum ada frame -> placeholder offline
            self._head("image/jpeg", len(jpg))
            self.wfile.write(jpg)
            return
        if path.startswith("/stream/"):
            cam = path.split("/", 2)[2]
            self._head("multipart/x-mixed-replace; boundary=frame")
            last_ver = -1
            last_ph = 0.0
            try:
                while True:
                    with _lock:
                        ver = _versions.get(cam, 0)
                        jpg = _frames.get(cam) if ver != last_ver else None
                    if jpg is not None:
                        last_ver = ver
                    elif ver == 0 and (time.time() - last_ph) > 1.0:
                        # Kamera belum pernah kirim frame (sumber offline) -> heartbeat
                        # placeholder tiap 1s supaya <img> tak menggantung hitam.
                        last_ph = time.time()
                        jpg = _placeholder_jpeg(cam)
                    if jpg is not None:
                        self.wfile.write(
                            b"--frame\r\nContent-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n"
                            + jpg + b"\r\n"
                        )
                        self.wfile.flush()
                    else:
                        time.sleep(0.02)   # tunggu frame baru (mendekati realtime)
            except (BrokenPipeError, ConnectionResetError):
                return
            return
        self.send_error(404)


def start(port):
    srv = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True, name="stream").start()
    log.info("Stream MJPEG aktif di :%d  (/stream/<cam>, /snapshot/<cam>)", port)
