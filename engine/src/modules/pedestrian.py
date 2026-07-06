"""Modul Pedestrian — PAR (atribut) + Re-ID (lintas kamera).

Berbasis perception DeepStream: DeepStream mendeteksi & melacak 'person',
mengirim objek (track_id, bbox, crop opsional) ke MQTT. Worker ini menjalankan
model PAR pada crop untuk 11 atribut, dan model embedding untuk Re-ID antar kamera.

>>> COLOKKAN MODEL ANDA di load_models() dan _run_par()/_run_reid(). <<<
"""
import base64
import logging

import numpy as np

from .base import PerceptionWorker
from ..onnx_util import load_session

log = logging.getLogger("engine.pedestrian")


class PedestrianWorker(PerceptionWorker):
    code = "pedestrian"
    relevant_classes = ("person",)

    def load_models(self, models_dir):
        self.par = load_session(self._model_path("par_pa100k.onnx"))
        self.reid = load_session(self._model_path("reid_osnet.onnx"))
        self.ready = self.par is not None
        # galeri embedding Re-ID: global_id -> vektor (untuk matching sederhana)
        self._gallery = {}
        self._next_global_id = 1

    def process(self, camera_id, ts, objects):
        if not self.ready:
            return
        for obj in objects:
            crop = self._decode_crop(obj.get("crop"))
            if crop is None:
                continue
            attributes = self._run_par(crop)            # dict 11 atribut
            global_id, reid_score = self._match_reid(crop)
            data = {
                "trackId": obj.get("trackId"),
                "globalId": global_id,
                "attributes": attributes,
                "bbox": obj.get("bbox"),
                "parScore": attributes.pop("_score", None) if attributes else None,
                "reidScore": reid_score,
            }
            self.emit(camera_id, "track", data, obj.get("confidence"))

    # --- util ---
    def _decode_crop(self, b64):
        if not b64:
            return None
        try:
            import cv2
            buf = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
            return cv2.imdecode(buf, cv2.IMREAD_COLOR)
        except Exception:
            return None

    def _run_par(self, crop):
        # === TODO: preprocess crop -> self.par.run(...) -> map ke 11 atribut ===
        return {}

    def _match_reid(self, crop):
        # === TODO: embedding = self.reid.run(...); cosine match ke self._gallery ===
        # Kembalikan (global_id, skor). Default: belum match.
        return None, None
