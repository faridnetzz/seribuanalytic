"""State bersama FR: FaceEngine + Gallery (singleton) + frame mentah per kamera.

Dipakai pedestrian (produsen frame + pemilik FR) dan enroll (konsumen: capture
wajah dari frame kamera lalu daftarkan).
"""
import threading

face_engine = None     # FaceEngine (insightface)
gallery = None         # Gallery (galeri enrollment)

_raw = {}              # cam_id -> frame BGR mentah terbaru (tanpa anotasi)
_lock = threading.Lock()


def set_raw(cam, frame):
    with _lock:
        _raw[cam] = frame


def get_raw(cam):
    with _lock:
        f = _raw.get(cam)
        return None if f is None else f.copy()
