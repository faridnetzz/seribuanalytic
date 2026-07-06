"""Sumber frame untuk modul berbasis citra penuh (air, sampah).

Mendukung dua sumber:
- RTSP  : stream kamera/NVR live (produksi).
- File  : video .mp4 lokal (dev/uji sebelum ada NVR) — di-loop saat habis.

Pengambilan ber-interval rendah (FRAME_INTERVAL_S) karena air/sampah tak perlu 30 FPS.
"""
import logging
import cv2

log = logging.getLogger("engine.frame")


class FrameSource:
    def __init__(self, spec: dict):
        # spec = {"type": "file"|"rtsp", "path": ...}
        self.spec = spec
        self._cap = None

    def _open(self):
        if self.spec["type"] == "file":
            self._cap = cv2.VideoCapture(self.spec["path"])
        else:
            # FFMPEG + TCP lebih stabil untuk RTSP kota.
            self._cap = cv2.VideoCapture(self.spec["path"], cv2.CAP_FFMPEG)

    def _ensure(self):
        if self._cap is None or not self._cap.isOpened():
            self._open()
        return self._cap is not None and self._cap.isOpened()

    def grab(self):
        """Ambil 1 frame (BGR ndarray) atau None bila gagal."""
        if not self._ensure():
            log.warning("Tidak bisa membuka sumber: %s", self.spec)
            return None
        ok, frame = self._cap.read()
        if not ok:
            # File habis -> ulangi dari awal (loop). RTSP gagal -> reset koneksi.
            if self.spec["type"] == "file":
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._cap.read()
                if ok:
                    return frame
            self.release()
            return None
        return frame

    def release(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None
