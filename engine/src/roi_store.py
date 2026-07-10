"""Penyimpanan ROI parkir per kamera (polygon ternormalisasi 0..1) + ambang
waktu pelanggaran (dwell) per kamera — dapat diubah dari dashboard.

ROI & ambang digambar/diatur di dashboard lalu di-POST ke engine (port 8090).
Persist ke file JSON di volume (config.ROI_FILE) supaya bertahan lintas restart.

Format file (baru): { "<cam>": {"polygon": [[x,y],...], "dwellSeconds": 120} }
Format lama (list polygon saja) tetap dibaca demi kompatibilitas.
"""
import json
import logging
import os
import threading

from . import config

log = logging.getLogger("engine.roi")

_lock = threading.Lock()
_rois = {}      # cam_id -> [[x,y], ...] ternormalisasi 0..1
_dwell = {}     # cam_id -> ambang detik (override config.PARK_DWELL_S)


def load():
    global _rois, _dwell
    try:
        if os.path.exists(config.ROI_FILE):
            with open(config.ROI_FILE) as f:
                raw = json.load(f)
            for cam, val in (raw or {}).items():
                if isinstance(val, dict):                 # format baru
                    if val.get("polygon"):
                        _rois[cam] = val["polygon"]
                    if val.get("dwellSeconds"):
                        _dwell[cam] = int(val["dwellSeconds"])
                elif isinstance(val, list):               # format lama (polygon saja)
                    _rois[cam] = val
            log.info("ROI dimuat untuk: %s (dwell custom: %s)",
                     list(_rois.keys()), _dwell)
    except Exception as e:
        log.error("Gagal memuat ROI: %s", e)


def _persist():
    try:
        os.makedirs(os.path.dirname(config.ROI_FILE), exist_ok=True)
        out = {}
        for cam in set(_rois) | set(_dwell):
            out[cam] = {"polygon": _rois.get(cam, []),
                        "dwellSeconds": _dwell.get(cam)}
        with open(config.ROI_FILE, "w") as f:
            json.dump(out, f)
    except Exception as e:
        log.error("Gagal menyimpan ROI: %s", e)


def _default_zone(cam):
    """Zona bawaan dari config.PARKING_ZONES — dipakai HANYA bila belum ada ROI yang
    digambar/di-load utk kamera ini. Supaya deployment baru (roi.json kosong, mis. di
    server) langsung punya zona parkir berfungsi tanpa harus gambar manual dulu.
    Tetap bisa ditimpa penuh via 'Atur ROI' di dashboard (set_roi menyimpan ke _rois)."""
    zones = getattr(config, "PARKING_ZONES", {}).get(cam) or []
    return zones[0] if zones else None


def get(cam):
    with _lock:
        if cam in _rois:
            return _rois[cam]
    z = _default_zone(cam)
    return z.get("polygon") if z else None


def all_rois():
    with _lock:
        return dict(_rois)


def get_dwell(cam):
    """Ambang detik pelanggaran utk kamera ini (None bila pakai default global)."""
    with _lock:
        return _dwell.get(cam)


def set_roi(cam, polygon, dwell_seconds=None):
    """polygon = list [[x,y],...] ternormalisasi. dwell_seconds opsional (ambang
    pelanggaran detik). Keduanya disimpan & di-persist."""
    with _lock:
        if polygon:
            _rois[cam] = polygon
        else:
            _rois.pop(cam, None)              # polygon kosong = hapus ROI
        if dwell_seconds is not None:
            try:
                d = int(dwell_seconds)
                if d > 0:
                    _dwell[cam] = d
            except (TypeError, ValueError):
                pass
        _persist()
    log.info("ROI %s diperbarui (%d titik, dwell=%s)", cam,
             len(polygon or []), _dwell.get(cam))
