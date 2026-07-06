"""Galeri snapshot (ala oss_vision): auto-simpan crop tubuh+wajah tiap orang
terdeteksi + metadata (waktu, kamera, gender, usia, identitas). Klik di dashboard
-> enroll (crop wajah jadi foto enrollment).

Penyimpanan: gambar di SNAP_DIR/<id>_body.jpg & _face.jpg; metadata FIFO (SNAP_MAX)
di SNAP_DIR/meta.json (persist).
"""
import json
import logging
import os
import shutil
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np

from . import config

log = logging.getLogger("engine.snapshots")
_WIB = timezone(timedelta(hours=7))
_lock = threading.Lock()
_items = []                       # snapshot pedestrian (metadata), terbaru di depan
_META = os.path.join(config.SNAP_DIR, "meta.json")
_park = []                        # snapshot pelanggaran parkir (FIFO terpisah)
_PARK_META = os.path.join(config.SNAP_DIR, "park_meta.json")
_waste = []                       # snapshot tumpukan sampah (FIFO terpisah)
_WASTE_META = os.path.join(config.SNAP_DIR, "waste_meta.json")
_identities = []                  # [{gid, e:face_emb|None, sig:body_hist|None, ts}] identitas global aktif (utk match lintas-kamera)
_sightings = {}                   # gid -> [{cam, ts(iso), t(epoch)}] = JEJAK lintas-kamera (trajectory)
_SIGHT = os.path.join(config.SNAP_DIR, "sightings.json")


def load():
    global _items, _park, _waste, _sightings
    try:
        if os.path.exists(_META):
            with open(_META) as f:
                _items = json.load(f)
        if os.path.exists(_PARK_META):
            with open(_PARK_META) as f:
                _park = json.load(f)
        if os.path.exists(_WASTE_META):
            with open(_WASTE_META) as f:
                _waste = json.load(f)
        if os.path.exists(_SIGHT):
            with open(_SIGHT) as f:
                _sightings = json.load(f)
        log.info("Snapshot dimuat: %d pedestrian, %d parkir, %d sampah, %d trajektori",
                 len(_items), len(_park), len(_waste), len(_sightings))
    except Exception as e:
        log.error("Gagal memuat snapshot: %s", e)


def _persist():
    try:
        os.makedirs(config.SNAP_DIR, exist_ok=True)
        with open(_META, "w") as f:
            json.dump(_items[:config.SNAP_MAX], f)
    except Exception as e:
        log.error("persist snapshot: %s", e)


def add(cam, body_img, face_img, meta, scene_img=None):
    """Simpan snapshot: foto PANORAMA penuh (frame utuh + bounding box orang, tak
    burik saat objek jauh) + crop tubuh + crop wajah. `scene_img` = frame penuh
    sudah tergambar box/label PAR (opsional)."""
    sid = uuid.uuid4().hex[:12]
    os.makedirs(config.SNAP_DIR, exist_ok=True)
    q = [cv2.IMWRITE_JPEG_QUALITY, 95]
    cv2.imwrite(os.path.join(config.SNAP_DIR, sid + "_body.jpg"), body_img, q)
    has_face = face_img is not None and getattr(face_img, "size", 0) > 0
    if has_face:
        cv2.imwrite(os.path.join(config.SNAP_DIR, sid + "_face.jpg"), face_img, q)
    has_scene = scene_img is not None and getattr(scene_img, "size", 0) > 0
    if has_scene:
        cv2.imwrite(os.path.join(config.SNAP_DIR, sid + "_scene.jpg"), scene_img,
                    [cv2.IMWRITE_JPEG_QUALITY, 88])   # frame besar -> kompresi sedikit
    rec = {"id": sid, "ts": datetime.now(_WIB).isoformat(), "cam": cam,
           "hasFace": bool(has_face), "hasScene": bool(has_scene), **meta}
    with _lock:
        _items.insert(0, rec)
        while len(_items) > config.SNAP_MAX:
            old = _items.pop()
            for suf in ("_body.jpg", "_face.jpg", "_scene.jpg"):
                try:
                    os.remove(os.path.join(config.SNAP_DIR, old["id"] + suf))
                except OSError:
                    pass
        _persist()
    return sid


def list_items(cam=None, identity=None, limit=240):
    with _lock:
        out = list(_items)
    if cam:
        out = [r for r in out if r.get("cam") == cam]
    if identity == "known":
        out = [r for r in out if r.get("name")]
    elif identity == "unknown":
        out = [r for r in out if not r.get("name")]
    return out[:limit]


def img_path(sid, kind="body"):
    p = os.path.join(config.SNAP_DIR, f"{sid}_{kind}.jpg")
    return p if os.path.exists(p) else None


def _body_sig(img):
    """Tanda-tangan penampilan tubuh = histogram warna HSV (Hue+Sat) ternormalisasi.
    Murah (CPU), tahan pose, TANPA wajah -> dedup orang sama walau track ID ganti."""
    if img is None or getattr(img, "size", 0) == 0:
        return None
    try:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h = cv2.calcHist([hsv], [0, 1], None, [20, 20], [0, 180, 0, 256]).flatten().astype(np.float32)
        n = np.linalg.norm(h)
        return h / n if n > 0 else None
    except Exception:
        return None


def _persist_sightings():
    try:
        os.makedirs(config.SNAP_DIR, exist_ok=True)
        with open(_SIGHT, "w") as f:
            json.dump(_sightings, f)
    except Exception as e:
        log.error("persist sightings: %s", e)


def register_sighting(cam, emb, body_img, ts_iso):
    """Cocokkan orang ke IDENTITAS GLOBAL (lintas-kamera) via wajah (kuat) / warna
    tubuh (saat tanpa wajah), lalu catat SIGHTING (kamera, waktu) -> trajektori.

    Return (gid, is_new):
      - is_new True  = identitas baru -> layak SIMPAN snapshot baru di galeri.
      - is_new False = orang yg sama (mungkin di kamera lain) -> JANGAN simpan foto
        lagi (anti-dobel), tapi sighting tetap dicatat utk jejak lintas-kamera.
    """
    now = time.time()
    e = None
    if emb is not None:
        e = np.asarray(emb, dtype=np.float32)
        n = np.linalg.norm(e)
        e = e / n if n > 0 else None
    sig = _body_sig(body_img)
    global _identities
    win = max(config.SNAP_DEDUP_WINDOW, config.SNAP_BODY_WINDOW)
    gid = None
    with _lock:
        _identities = [d for d in _identities if now - d["ts"] < win]
        for d in _identities:
            face_ok = (e is not None and d["e"] is not None
                       and now - d["ts"] < config.SNAP_DEDUP_WINDOW
                       and float(np.dot(d["e"], e)) >= config.SNAP_DEDUP_THRESH)
            body_ok = (sig is not None and d["sig"] is not None
                       and now - d["ts"] < config.SNAP_BODY_WINDOW
                       and float(np.dot(d["sig"], sig)) >= config.SNAP_BODY_THRESH)
            if face_ok or body_ok:
                gid = d["gid"]
                d["ts"] = now
                if e is not None:
                    d["e"] = e                       # perbarui sidik terbaru
                if sig is not None:
                    d["sig"] = sig
                break
        is_new = gid is None
        if is_new:
            gid = uuid.uuid4().hex[:12]
            _identities.append({"gid": gid, "e": e, "sig": sig, "ts": now})
            if len(_identities) > 400:
                del _identities[:len(_identities) - 400]
        # catat sighting (1 per kunjungan-kamera; perpanjang bila kamera sama < gap)
        lst = _sightings.setdefault(gid, [])
        if lst and lst[-1]["cam"] == cam and now - lst[-1]["t"] < config.SIGHT_GAP_S:
            lst[-1]["ts"] = ts_iso
            lst[-1]["t"] = now
        else:
            lst.append({"cam": cam, "ts": ts_iso, "t": now})
            if len(lst) > 100:
                del lst[:len(lst) - 100]
        _persist_sightings()
    return gid, is_new


def list_sightings(gid):
    """Jejak lintas-kamera satu identitas: [{cam, ts}] urut waktu."""
    with _lock:
        out = list(_sightings.get(gid, []))
    return [{"cam": s["cam"], "ts": s["ts"]} for s in sorted(out, key=lambda s: s["t"])]


# ---- snapshot pelanggaran parkir (store terpisah) ----
def _persist_park():
    try:
        os.makedirs(config.SNAP_DIR, exist_ok=True)
        with open(_PARK_META, "w") as f:
            json.dump(_park[:config.PARK_SNAP_MAX], f)
    except Exception as e:
        log.error("persist park snapshot: %s", e)


def add_parking(cam, vehicle_img, meta):
    """Simpan crop kendaraan saat pertama jadi pelanggaran (>2 menit di ROI)."""
    sid = uuid.uuid4().hex[:12]
    os.makedirs(config.SNAP_DIR, exist_ok=True)
    cv2.imwrite(os.path.join(config.SNAP_DIR, sid + "_body.jpg"),
                vehicle_img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    rec = {"id": sid, "ts": datetime.now(_WIB).isoformat(), "cam": cam,
           "kind": "parking", **meta}
    with _lock:
        _park.insert(0, rec)
        while len(_park) > config.PARK_SNAP_MAX:
            old = _park.pop()
            try:
                os.remove(os.path.join(config.SNAP_DIR, old["id"] + "_body.jpg"))
            except OSError:
                pass
        _persist_park()
    log.info("Snapshot pelanggaran parkir: %s %s (%ss)", cam,
             meta.get("vehicleType"), meta.get("dwellSeconds"))
    return sid


def update_parking(sid, dwell_seconds=None, departed=False):
    """Finalisasi snapshot pelanggaran saat kendaraan pergi: set durasi TOTAL
    (mulai-diam s/d pergi) + tandai sudah pergi. Dipanggil sekali per sesi."""
    if not sid:
        return
    with _lock:
        for r in _park:
            if r["id"] == sid:
                if dwell_seconds is not None:
                    r["dwellSeconds"] = int(dwell_seconds)
                if departed:
                    r["departedAt"] = datetime.now(_WIB).isoformat()
                break
        _persist_park()


def list_parking(cam=None, limit=120):
    with _lock:
        out = list(_park)
    if cam:
        out = [r for r in out if r.get("cam") == cam]
    return out[:limit]


def delete_parking(sid):
    """Hapus satu snapshot pelanggaran parkir (foto + metadata)."""
    global _park
    with _lock:
        _park = [r for r in _park if r["id"] != sid]
        _persist_park()
    try:
        os.remove(os.path.join(config.SNAP_DIR, sid + "_body.jpg"))
    except OSError:
        pass
    return {"ok": True}


def clear_parking():
    """Hapus SEMUA snapshot pelanggaran parkir (foto + metadata)."""
    global _park
    with _lock:
        ids = [r["id"] for r in _park]
        _park = []
        _persist_park()
    for sid in ids:
        try:
            os.remove(os.path.join(config.SNAP_DIR, sid + "_body.jpg"))
        except OSError:
            pass
    return {"ok": True, "deleted": len(ids)}


# ---- snapshot tumpukan sampah (store terpisah) ----
def _persist_waste():
    try:
        os.makedirs(config.SNAP_DIR, exist_ok=True)
        with open(_WASTE_META, "w") as f:
            json.dump(_waste[:config.PARK_SNAP_MAX], f)
    except Exception as e:
        log.error("persist waste snapshot: %s", e)


def add_waste(cam, pile_img, meta):
    """Simpan crop tumpukan sampah saat pertama muncul. Return sid (= pile_uid)."""
    sid = uuid.uuid4().hex[:12]
    os.makedirs(config.SNAP_DIR, exist_ok=True)
    cv2.imwrite(os.path.join(config.SNAP_DIR, sid + "_body.jpg"),
                pile_img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    rec = {"id": sid, "ts": datetime.now(_WIB).isoformat(), "cam": cam,
           "kind": "waste", **meta}
    with _lock:
        _waste.insert(0, rec)
        while len(_waste) > config.PARK_SNAP_MAX:
            old = _waste.pop()
            try:
                os.remove(os.path.join(config.SNAP_DIR, old["id"] + "_body.jpg"))
            except OSError:
                pass
        _persist_waste()
    return sid


def update_waste(sid, **fields):
    """Perbarui metadata snapshot tumpukan (durasi/severity/cleared) saat heartbeat/diangkut."""
    if not sid:
        return
    with _lock:
        for r in _waste:
            if r["id"] == sid:
                r.update(fields)
                break
        _persist_waste()


def list_waste(cam=None, limit=120):
    with _lock:
        out = list(_waste)
    if cam:
        out = [r for r in out if r.get("cam") == cam]
    return out[:limit]


def delete_waste(sid):
    global _waste
    with _lock:
        _waste = [r for r in _waste if r["id"] != sid]
        _persist_waste()
    try:
        os.remove(os.path.join(config.SNAP_DIR, sid + "_body.jpg"))
    except OSError:
        pass
    return {"ok": True}


def clear_waste():
    global _waste
    with _lock:
        ids = [r["id"] for r in _waste]
        _waste = []
        _persist_waste()
    for sid in ids:
        try:
            os.remove(os.path.join(config.SNAP_DIR, sid + "_body.jpg"))
        except OSError:
            pass
    return {"ok": True, "deleted": len(ids)}


def delete(sid):
    global _items
    with _lock:
        _items = [r for r in _items if r["id"] != sid]
        _persist()
    for suf in ("_body.jpg", "_face.jpg", "_scene.jpg"):
        try:
            os.remove(os.path.join(config.SNAP_DIR, sid + suf))
        except OSError:
            pass
    return {"ok": True}


def enroll_from(sid, name):
    """Jadikan wajah pada snapshot ini sebagai foto enrollment untuk <name>."""
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "Nama kosong"}
    face = img_path(sid, "face")
    if not face:
        return {"ok": False, "error": "Snapshot ini tidak punya wajah"}
    d = os.path.join(config.ENROLL_DIR, name)
    os.makedirs(d, exist_ok=True)
    shutil.copy(face, os.path.join(d, f"{sid}.jpg"))
    # tandai metadata snapshot sebagai sudah dikenali
    with _lock:
        for r in _items:
            if r["id"] == sid:
                r["name"] = name
        _persist()
    log.info("Enroll dari snapshot %s -> %s", sid, name)
    return {"ok": True, "name": name}
