"""Modul Parkir Liar — zona + dwell time.

Logika murni di atas tracking DeepStream (tanpa model tambahan). DeepStream
melacak kendaraan; worker ini mengukur berapa lama tiap track berada di dalam
poligon zona terlarang, lalu menerbitkan pelanggaran saat melewati ambang.
"""
import logging
import time

from .base import PerceptionWorker
from .. import config

log = logging.getLogger("engine.parking")

VEHICLE_CLASSES = ("car", "motorcycle", "bus", "truck", "mobil", "motor", "pickup")
RE_EMIT_S = 60  # kirim ulang pelanggaran aktif tiap 60 dtk


def point_in_polygon(x, y, poly):
    """Ray casting; poly = [[x,y],...] ternormalisasi 0..1."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi):
            inside = not inside
        j = i
    return inside


class ParkingWorker(PerceptionWorker):
    code = "parking"
    relevant_classes = VEHICLE_CLASSES

    def load_models(self, models_dir):
        # Tidak butuh model; murni geometri + tracking.
        self.ready = True
        self.zones = config.PARKING_ZONES
        # state per (camera, track_id): {start, last_seen, last_emit, zone}
        self._tracks = {}

    def process(self, camera_id, ts, objects):
        zones = self.zones.get(camera_id)
        if not zones:
            return
        now = time.time()
        for obj in objects:
            bbox = obj.get("bbox") or {}
            # titik referensi: tengah-bawah bbox (roda kendaraan)
            cx = bbox.get("x", 0) + bbox.get("w", 0) / 2
            cy = bbox.get("y", 0) + bbox.get("h", 0)
            zone = next((z for z in zones if point_in_polygon(cx, cy, z["polygon"])), None)
            if zone is None:
                continue

            key = (camera_id, obj.get("trackId"))
            st = self._tracks.get(key)
            if st is None:
                st = {"start": now, "last_emit": 0, "zone": zone["name"]}
                self._tracks[key] = st
            st["last_seen"] = now

            dwell = int(now - st["start"])
            over_limit = dwell >= zone["dwell_limit_s"]
            due_reemit = (now - st["last_emit"]) >= RE_EMIT_S
            if over_limit and due_reemit:
                st["last_emit"] = now
                self.emit(camera_id, "violation", {
                    "zoneName": zone["name"],
                    "vehicleType": _norm_vehicle(obj.get("class")),
                    "dwellSeconds": dwell,
                    "bbox": bbox,
                    "status": "active",
                }, obj.get("confidence"))

        self._expire(now)

    def _expire(self, now, timeout=15):
        """Bersihkan track yang tak terlihat > timeout detik."""
        gone = [k for k, st in self._tracks.items() if now - st.get("last_seen", now) > timeout]
        for k in gone:
            del self._tracks[k]


def _norm_vehicle(cls):
    return {"car": "mobil", "motorcycle": "motor", "truck": "truk", "bus": "bus"}.get(cls, cls)
