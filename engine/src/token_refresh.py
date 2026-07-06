"""Auto-refresh token kamera seribuwajah.

stream_id (token `stream?key=`) tiap kamera berubah berkala -> stream mati.
Endpoint publik https://beseribuwajah.bandarlampungkota.go.id/cctv-public/ selalu
mengembalikan stream_id TERBARU per kamera. Modul ini:
  - map CAM-ID -> nama kamera (config.CAM_NAMES)
  - ambil stream_id terbaru -> update config.LIVE_CAMERAS[cam]
Proxy HLS membaca config.LIVE_CAMERAS tiap request, jadi reader otomatis pakai
token baru begitu reconnect. Refresh: saat start, periodik, dan saat stream putus.
"""
import json
import logging
import threading
import time
import urllib.request

from . import config

log = logging.getLogger("engine.token")

CCTV_PUBLIC = "https://beseribuwajah.bandarlampungkota.go.id/cctv-public/"
HEADERS = {"User-Agent": "Mozilla/5.0",
           "Referer": "https://seribuwajah.bandarlampungkota.go.id/"}
_last = 0.0
_lock = threading.Lock()


def refresh(force=False):
    """Ambil stream_id terbaru, update config.LIVE_CAMERAS. Di-throttle."""
    global _last
    with _lock:
        if not force and time.time() - _last < config.TOKEN_REFRESH_MIN_GAP:
            return
        _last = time.time()
    try:
        req = urllib.request.Request(CCTV_PUBLIC, headers=HEADERS)
        data = json.load(urllib.request.urlopen(req, timeout=15))
        items = data if isinstance(data, list) else data.get("results", [])
        by_name = {c.get("nama"): c.get("stream_id") for c in items}
        changed = []
        for cam, name in config.CAM_NAMES.items():
            sid = by_name.get(name)
            if not sid:
                continue
            url = config._BASE + str(sid)
            if config.LIVE_CAMERAS.get(cam) != url:
                config.LIVE_CAMERAS[cam] = url
                changed.append(f"{cam}={sid}")
        if changed:
            log.info("Token diperbarui: %s", ", ".join(changed))
    except Exception as e:
        log.error("Gagal refresh token: %s", e)


def start():
    refresh(force=True)                       # sebelum reader mulai
    def loop():
        while True:
            time.sleep(config.TOKEN_REFRESH_INTERVAL)
            refresh(force=True)
    threading.Thread(target=loop, daemon=True, name="token-refresh").start()
    log.info("Auto-refresh token aktif (periodik tiap %ds)",
             int(config.TOKEN_REFRESH_INTERVAL))
