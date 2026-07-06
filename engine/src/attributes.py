"""Ekstraksi atribut pejalan kaki (PAR) — port dari oss_vision_stage1.

Pendekatan pragmatis tanpa model PAR terlatih (sama persis oss_vision):
  - Gender + Usia → dari InsightFace (di seribuwajah: dipasok pipeline FR yang
    sudah jalan, jadi TANPA beban GPU tambahan). Lihat pedestrian.py.
  - Warna atasan/bawahan → histogram HSV pada crop torso/kaki → nama warna.
  - Aksesori → heuristik: topi (kontras warna 12% teratas bbox), tas (rasio
    aspek bbox), masker (kerataan landmark mulut wajah — dari FR).

Semua extractor best-effort: crop kecil / data tak ada → None, bukan exception.
Atribut diakumulasi per-track lintas frame (merge_attribute_samples) lalu
direduksi ke nilai final (summarize_attributes: modus utk kategori, rata-rata
utk umur) supaya stabil — tidak goyang oleh deteksi awal yang noisy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import cv2
import numpy as np


# ─── Hasil ekstraksi 1 frame utk 1 orang ─────────────────────────────────────
@dataclass
class PersonAttributeSnapshot:
    gender: Optional[str] = None            # 'L' | 'P' (Laki/Perempuan)
    gender_confidence: float = 0.0
    age_estimate: Optional[int] = None
    clothing_top_color: Optional[str] = None
    clothing_bottom_color: Optional[str] = None
    accessories: list[str] = field(default_factory=list)


# ─── Penamaan warna (bucket HSV → label) ─────────────────────────────────────
# HSV OpenCV: H∈[0,179], S∈[0,255], V∈[0,255]
_COLOR_BUCKETS: list[tuple[str, int, int]] = [
    ("merah", 0, 9), ("oranye", 10, 22), ("kuning", 23, 33), ("hijau", 34, 78),
    ("sian", 79, 95), ("biru", 96, 130), ("ungu", 131, 158), ("merah", 159, 179),
]


def _classify_color_patch(patch_bgr: np.ndarray) -> Optional[str]:
    """Klasifikasi warna dominan satu patch BGR -> hitam/putih/abu/<warna>/None."""
    if patch_bgr is None or patch_bgr.size == 0:
        return None
    try:
        hsv = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2HSV)
    except Exception:
        return None
    h = hsv[:, :, 0].flatten()
    s = hsv[:, :, 1].flatten()
    v = hsv[:, :, 2].flatten()
    if v.size == 0:
        return None
    mean_v = float(np.mean(v))
    mean_s = float(np.mean(s))
    if mean_v < 50 and mean_s < 60:
        return "hitam"
    if mean_v > 210 and mean_s < 35:
        return "putih"
    if mean_s < 35:
        return "abu"
    valid_mask = (s > 50) & (v > 50)
    valid_hues = h[valid_mask]
    if valid_hues.size == 0:
        if mean_v < 90:
            return "hitam"
        if mean_v > 190:
            return "putih"
        return "abu"
    hist, _ = np.histogram(valid_hues, bins=180, range=(0, 180))
    dominant_hue = int(np.argmax(hist))
    for name, hmin, hmax in _COLOR_BUCKETS:
        if hmin <= dominant_hue <= hmax:
            return name
    return None


def _crop_safe(frame: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> Optional[np.ndarray]:
    h, w = frame.shape[:2]
    x1 = max(0, min(int(x1), w - 1))
    x2 = max(0, min(int(x2), w))
    y1 = max(0, min(int(y1), h - 1))
    y2 = max(0, min(int(y2), h))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    return frame[y1:y2, x1:x2]


# ─── Age group ───────────────────────────────────────────────────────────────
def map_age_to_group(age: Optional[int]) -> Optional[str]:
    if age is None:
        return None
    if age < 14:
        return "anak"
    if age < 25:
        return "remaja"
    if age < 60:
        return "dewasa"
    return "lansia"


# ─── Aksesori (heuristik) ────────────────────────────────────────────────────
def detect_hat(frame: np.ndarray, bbox: tuple[int, int, int, int]) -> bool:
    """Topi/helm: 12% teratas bbox warnanya beda jelas dari band 15-35%."""
    x1, y1, x2, y2 = bbox
    h_bbox = y2 - y1
    if h_bbox < 80:
        return False
    head_top = _crop_safe(frame, x1, y1, x2, y1 + int(h_bbox * 0.12))
    head_mid = _crop_safe(frame, x1, y1 + int(h_bbox * 0.15), x2, y1 + int(h_bbox * 0.35))
    if head_top is None or head_mid is None:
        return False
    try:
        top_hsv = cv2.cvtColor(head_top, cv2.COLOR_BGR2HSV)
        mid_hsv = cv2.cvtColor(head_mid, cv2.COLOR_BGR2HSV)
    except Exception:
        return False
    top_mean = top_hsv.reshape(-1, 3).mean(axis=0)
    mid_mean = mid_hsv.reshape(-1, 3).mean(axis=0)
    hue_diff = min(abs(top_mean[0] - mid_mean[0]), 180 - abs(top_mean[0] - mid_mean[0]))
    sat_diff = abs(top_mean[1] - mid_mean[1])
    val_diff = abs(top_mean[2] - mid_mean[2])
    return bool((hue_diff > 18 and top_mean[1] > 60) or sat_diff > 70 or val_diff > 70)


def detect_bag(bbox: tuple[int, int, int, int]) -> bool:
    """Tas: rasio lebar/tinggi bbox > 0.65 (berdiri biasa ~0.4-0.5)."""
    x1, y1, x2, y2 = bbox
    w = x2 - x1
    h = y2 - y1
    if h <= 0:
        return False
    return (w / h) > 0.65


def mask_from_landmark(landmark_2d_106: Any) -> bool:
    """Masker: titik-titik mulut sangat datar (std-y < 1.5) -> tertutup masker.
    landmark_2d_106 dari InsightFace Face. None/kurang titik -> False."""
    if landmark_2d_106 is None or len(landmark_2d_106) < 71:
        return False
    try:
        mouth_pts = landmark_2d_106[52:71]
        mouth_y_std = float(np.std([p[1] for p in mouth_pts]))
        return mouth_y_std < 1.5
    except Exception:
        return False


# ─── Extractor utama (CPU: warna baju + topi/tas) ────────────────────────────
def extract_attributes(
    frame: np.ndarray,
    bbox: tuple[int, int, int, int],
    *,
    extract_clothing: bool = True,
    extract_accessories: bool = True,
) -> PersonAttributeSnapshot:
    """Ekstrak warna baju + aksesori (topi/tas) dari 1 person bbox. Murni CPU.
    Gender/usia/masker dipasok terpisah (dari FR) lalu di-merge."""
    snap = PersonAttributeSnapshot()
    x1, y1, x2, y2 = bbox
    h_bbox = y2 - y1
    w_bbox = x2 - x1
    if h_bbox < 60 or w_bbox < 25:
        return snap  # terlalu kecil utk reliable

    if extract_clothing:
        # Atasan: 30%-55% bbox (torso)
        tp = _crop_safe(frame, x1 + int(w_bbox * 0.20), y1 + int(h_bbox * 0.30),
                        x2 - int(w_bbox * 0.20), y1 + int(h_bbox * 0.55))
        if tp is not None:
            snap.clothing_top_color = _classify_color_patch(tp)
        # Bawahan: 60%-90% bbox (kaki/celana)
        bp = _crop_safe(frame, x1 + int(w_bbox * 0.25), y1 + int(h_bbox * 0.60),
                        x2 - int(w_bbox * 0.25), y1 + int(h_bbox * 0.90))
        if bp is not None:
            snap.clothing_bottom_color = _classify_color_patch(bp)

    if extract_accessories:
        acc: list[str] = []
        try:
            if detect_hat(frame, bbox):
                acc.append("topi")
        except Exception:
            pass
        try:
            if detect_bag(bbox):
                acc.append("tas")
        except Exception:
            pass
        snap.accessories = acc

    return snap


# ─── Agregasi lintas frame (per track) ───────────────────────────────────────
def merge_attribute_samples(samples: dict[str, Any], snap: PersonAttributeSnapshot) -> None:
    """Akumulasi observasi baru ke `samples` (mutable).
    Schema: gender{L,P:int}, age[list int], top_color{name:int},
    bottom_color{name:int}, accessory{topi,tas,masker:int}."""
    if snap.gender:
        g = samples.setdefault("gender", {})
        g[snap.gender] = int(g.get(snap.gender, 0)) + 1
    if snap.age_estimate is not None:
        ages = samples.setdefault("age", [])
        ages.append(int(snap.age_estimate))
        if len(ages) > 30:
            samples["age"] = ages[-30:]
    if snap.clothing_top_color:
        t = samples.setdefault("top_color", {})
        t[snap.clothing_top_color] = int(t.get(snap.clothing_top_color, 0)) + 1
    if snap.clothing_bottom_color:
        b = samples.setdefault("bottom_color", {})
        b[snap.clothing_bottom_color] = int(b.get(snap.clothing_bottom_color, 0)) + 1
    if snap.accessories:
        a = samples.setdefault("accessory", {})
        for acc in snap.accessories:
            a[acc] = int(a.get(acc, 0)) + 1


def summarize_attributes(samples: dict[str, Any], min_samples: int = 1) -> dict[str, Any]:
    """Reduksi samples ke nilai final (modus utk kategori, rata-rata utk umur).
    Atribut dgn sample < min_samples di-skip (hindari noise deteksi awal)."""
    result: dict[str, Any] = {
        "gender": None, "gender_confidence": 0.0, "age_estimate": None,
        "age_group": None, "clothing_top_color": None,
        "clothing_bottom_color": None, "accessories": [],
    }
    gc = samples.get("gender") or {}
    if gc:
        total = sum(gc.values())
        if total >= min_samples:
            best_g, best_c = max(gc.items(), key=lambda kv: kv[1])
            result["gender"] = best_g
            result["gender_confidence"] = float(best_c) / max(1, total)
    ages = samples.get("age") or []
    if len(ages) >= min_samples:
        avg = int(round(sum(ages) / len(ages)))
        result["age_estimate"] = avg
        result["age_group"] = map_age_to_group(avg)
    tc = samples.get("top_color") or {}
    if sum(tc.values()) >= min_samples:
        result["clothing_top_color"] = max(tc.items(), key=lambda kv: kv[1])[0]
    bc = samples.get("bottom_color") or {}
    if sum(bc.values()) >= min_samples:
        result["clothing_bottom_color"] = max(bc.items(), key=lambda kv: kv[1])[0]
    ac = samples.get("accessory") or {}
    result["accessories"] = sorted([n for n, c in ac.items() if c >= min_samples])
    return result
