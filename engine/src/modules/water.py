"""Modul Debit Air Sungai — Virtual Staff Gauge (Ultralytics YOLO best.pt).

Ide: model mendeteksi garis permukaan air / penanda staff gauge. Posisi garis
air (y ternormalisasi) dikonversi ke ketinggian meter via kalibrasi linear per
kamera (lihat config.WATER_CALIBRATION), lalu ditentukan status & tren.

Taruh model di engine/models/ dengan nama `water.pt`. Selama belum ada, worker
jalan 'degraded'.

>>> Sesuaikan _waterline_y() dengan output kelas model Anda. <<<
"""
import logging
from collections import deque

from .base import FrameWorker
from .. import config
from ..yolo_util import load_yolo, infer

log = logging.getLogger("engine.water")

CONF_THRESHOLD = 0.30


class WaterWorker(FrameWorker):
    code = "water"
    default_event_type = "reading"

    def load_models(self, models_dir):
        self.model = load_yolo(self._model_path("water.pt"))
        self.ready = self.model is not None
        self._history = {}  # camera_id -> deque level terakhir (untuk tren)

    def _status(self, level_m):
        if level_m >= 2.0:
            return "bahaya"
        if level_m >= 1.5:
            return "siaga"
        if level_m >= 1.1:
            return "waspada"
        return "aman"

    def _waterline_y(self, frame, res):
        """Posisi garis air, y ternormalisasi 0..1 (0=atas frame). None bila tak terdeteksi.

        Default: ambil tepi ATAS bounding box deteksi paling atas (garis air
        tertinggi). Sesuaikan bila modelmu pakai mask/keypoint/kelas khusus.
        """
        boxes = getattr(res, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return None
        h = frame.shape[0]
        tops = [float(b.xyxy[0][1].item()) / h for b in boxes]  # y1 ternormalisasi
        return min(tops)  # paling atas = muka air tertinggi

    def _level_from_y(self, camera_id, y_norm):
        cal = config.water_calibration(camera_id)
        # interpolasi linear: y=0 -> level_at_y0, y=1 -> level_at_y1
        return cal["level_at_y0"] + (cal["level_at_y1"] - cal["level_at_y0"]) * y_norm

    def infer(self, camera_id, frame):
        if self.model is None:
            return []
        res = infer(self.model, frame, conf=CONF_THRESHOLD)
        y = self._waterline_y(frame, res)
        if y is None:
            return []
        level_m = max(0.0, self._level_from_y(camera_id, y))

        hist = self._history.setdefault(camera_id, deque(maxlen=6))
        trend_cm = round((level_m - hist[0]) * 100, 1) if hist else 0.0
        hist.append(level_m)

        return [(
            {
                "levelM": round(level_m, 3),
                "status": self._status(level_m),
                "trendCm30min": trend_cm,
            },
            0.95,
        )]
