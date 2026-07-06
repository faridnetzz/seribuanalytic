"""Face Recognition — wrapper insightface antelopev2.

Deteksi wajah + embedding 512-dim (glintr100) + gender/usia (genderage).
Model di MODELS_DIR/insightface/models/antelopev2/ (di-mount via volume).
"""
import logging

import numpy as np

from . import config, gpu

log = logging.getLogger("engine.fr")


class FaceEngine:
    def __init__(self):
        self.app = None

    def load(self):
        try:
            from insightface.app import FaceAnalysis
            self.app = FaceAnalysis(
                name=config.FACE_MODEL_NAME,
                root=config.FACE_MODEL_ROOT,
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
            self.app.prepare(ctx_id=0, det_size=(config.FACE_DET_SIZE, config.FACE_DET_SIZE))
            log.info("FaceEngine siap (antelopev2, det_size=%d)", config.FACE_DET_SIZE)
        except Exception as e:
            log.error("Gagal memuat FaceEngine: %s", e)
            self.app = None
        return self.app is not None

    def analyze(self, frame):
        """Kembalikan list dict: {bbox[x1,y1,x2,y2], embedding(512 np float32),
        det_score, gender('L'/'P'), age, mask(bool)}.
        mask = heuristik landmark mulut (utk atribut PAR), best-effort."""
        if self.app is None:
            return []
        from .attributes import mask_from_landmark
        with gpu.lock:                       # serialize akses GPU (cegah konflik CUDA)
            faces = self.app.get(frame)
        out = []
        for f in faces:
            out.append({
                "bbox": [int(v) for v in f.bbox],
                "embedding": f.normed_embedding.astype(np.float32),
                "det_score": float(f.det_score),
                "gender": "L" if f.sex == "M" else "P",
                "age": int(f.age),
                "mask": mask_from_landmark(getattr(f, "landmark_2d_106", None)),
            })
        return out
