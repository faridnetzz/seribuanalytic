"""Modul Deteksi Sampah — Ultralytics YOLO (best.pt).

Mendukung model deteksi (bbox) maupun segmentasi (mask). Tingkat keparahan
dihitung dari proporsi area frame yang tertutup sampah.

Taruh model di engine/models/ dengan nama `waste.pt` (atau ubah di load_models).
Selama file belum ada, worker jalan 'degraded' (skip inferensi).
"""
import logging

from .base import FrameWorker
from ..yolo_util import load_yolo, infer, norm_bbox

log = logging.getLogger("engine.waste")

# 0.40 dari hasil tuning lapangan: <0.4 model kadang keluarkan bbox raksasa
# skor-rendah pada scene bersih/redup. 0.40 lebih bersih.
CONF_THRESHOLD = 0.40


class WasteWorker(FrameWorker):
    code = "waste"
    default_event_type = "detection"

    def load_models(self, models_dir):
        self.model = load_yolo(self._model_path("waste.pt"))
        self.ready = self.model is not None

    def _severity(self, area_ratio):
        if area_ratio >= 0.15:
            return "critical"
        if area_ratio >= 0.08:
            return "high"
        if area_ratio >= 0.03:
            return "medium"
        return "low"

    def infer(self, camera_id, frame):
        if self.model is None:
            return []
        h, w = frame.shape[:2]
        res = infer(self.model, frame, conf=CONF_THRESHOLD)
        results = []

        # Segmentasi: pakai luas mask. Deteksi: pakai luas bbox.
        if getattr(res, "masks", None) is not None and res.masks is not None:
            for i, mask in enumerate(res.masks.data):
                area_ratio = float(mask.sum().item()) / float(mask.shape[-1] * mask.shape[-2])
                box = res.boxes[i]
                results.append(self._make(area_ratio, box, w, h))
        else:
            for box in res.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                area_ratio = ((x2 - x1) * (y2 - y1)) / float(w * h)
                results.append(self._make(area_ratio, box, w, h))
        return results

    def _make(self, area_ratio, box, w, h):
        conf = float(box.conf[0].item())
        return (
            {
                "severity": self._severity(area_ratio),
                "areaRatio": round(area_ratio, 4),
                "bbox": norm_bbox(box.xyxy[0].tolist(), w, h),
                # is_floating: tandai bila modelmu punya kelas sampah-air; default False.
                "isFloating": False,
            },
            round(conf, 3),
        )
