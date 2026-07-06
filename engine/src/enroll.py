"""Enrollment wajah dari frame kamera live (ala oss_vision).

capture(): ambil frame mentah kamera -> deteksi wajah terbesar -> crop (beri margin)
           -> simpan ke ENROLL_DIR/<nama>/. Panggil beberapa kali utk banyak angle.
finish() : rebuild galeri -> FR langsung kenali identitas baru.
"""
import logging
import os
import time

import cv2

from . import config, fr_state

log = logging.getLogger("engine.enroll")


def capture(name, cam):
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "Nama kosong"}
    if fr_state.face_engine is None:
        return {"ok": False, "error": "FR belum siap"}
    frame = fr_state.get_raw(cam)
    if frame is None:
        return {"ok": False, "error": f"Tidak ada frame dari {cam}"}
    faces = fr_state.face_engine.analyze(frame)
    if not faces:
        return {"ok": False, "faces": 0, "error": "Tidak ada wajah terdeteksi"}

    # wajah terbesar = subjek
    f = max(faces, key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = f["bbox"]
    mx, my = int((x2 - x1) * 0.3), int((y2 - y1) * 0.3)   # margin biar dahi/dagu ikut
    x1, y1 = max(0, x1 - mx), max(0, y1 - my)
    x2, y2 = min(w, x2 + mx), min(h, y2 + my)
    crop = frame[y1:y2, x1:x2]

    d = os.path.join(config.ENROLL_DIR, name)
    os.makedirs(d, exist_ok=True)
    cv2.imwrite(os.path.join(d, f"{int(time.time() * 1000)}.jpg"), crop)
    saved = len([x for x in os.listdir(d) if x.lower().endswith((".jpg", ".png"))])
    log.info("Enroll capture '%s' dari %s (total %d foto)", name, cam, saved)
    return {"ok": True, "faces": len(faces), "saved": saved,
            "gender": f["gender"], "age": f["age"]}


def finish():
    if fr_state.gallery is None:
        return {"ok": False, "error": "Galeri belum siap"}
    fr_state.gallery.build()
    return {"ok": True, "identities": len(fr_state.gallery.names),
            "names": fr_state.gallery.names}


def list_enrolled():
    if not os.path.isdir(config.ENROLL_DIR):
        return []
    out = []
    for d in sorted(os.listdir(config.ENROLL_DIR)):
        p = os.path.join(config.ENROLL_DIR, d)
        if os.path.isdir(p):
            n = len([x for x in os.listdir(p) if x.lower().endswith((".jpg", ".png"))])
            out.append({"name": d, "photos": n})
    return out
