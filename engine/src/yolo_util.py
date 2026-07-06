"""Helper Ultralytics YOLO — muat best.pt & util parsing hasil.

Import ultralytics dilakukan lazy (di dalam fungsi) supaya modul tetap bisa
di-import / py_compile tanpa torch terpasang di lingkungan lokal.
"""
import logging

log = logging.getLogger("engine.yolo")


def load_yolo(model_path: str):
    """Muat model YOLO (.pt). Kembalikan objek model atau None bila gagal."""
    if not model_path:
        return None
    try:
        from ultralytics import YOLO
        model = YOLO(model_path)
        log.info("Model YOLO dimuat: %s", model_path)
        return model
    except Exception as e:
        log.error("Gagal memuat YOLO %s: %s", model_path, e)
        return None


def norm_bbox(xyxy, w, h):
    """xyxy piksel -> bbox ternormalisasi 0..1 {x,y,w,h}."""
    x1, y1, x2, y2 = xyxy
    return {
        "x": round(x1 / w, 4),
        "y": round(y1 / h, 4),
        "w": round((x2 - x1) / w, 4),
        "h": round((y2 - y1) / h, 4),
    }


def infer(model, frame, conf=0.35):
    """Jalankan deteksi/segmentasi 1 frame di GPU. Kembalikan Results pertama."""
    from . import gpu
    with gpu.lock:                           # serialize akses GPU
        return model(frame, conf=conf, device=0, verbose=False)[0]
