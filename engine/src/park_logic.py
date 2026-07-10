"""Logika inti PARKIR LIAR — MURNI (tanpa YOLO / frame / IO) supaya bisa diuji unit
di luar sistem (lihat engine/tests/test_park_logic.py).

parking.py memanggil ParkingTracker.update() dengan daftar deteksi kendaraan
(track_id + bbox) per frame; tes memberi skenario sintetis. Tidak ada dependensi
cv2/torch/numpy di sini — point-in-polygon & IoU ditulis plain-python.

Model occupancy per 'slot' (lokasi parkir). Deteksi dicocokkan ke slot terdekat by
jarak-pusat / IoU. Durasi diam kendaraan yg SAMA di slot >= ambang -> pelanggaran.
Sesi ditutup saat kendaraan pergi (grace menyerap kedipan deteksi / stream stall).
"""
from dataclasses import dataclass
import uuid


@dataclass
class ParkingParams:
    freeze_gap_s: float = 2.5     # jeda observasi > ini = freeze/stall -> tak dihitung dwell
    match_iou: float = 0.30       # ambang IoU cocokkan deteksi ke slot
    match_dist: float = 0.6       # ambang jarak-pusat (fraksi dimensi box) cocokkan ke slot
    move_frac: float = 0.5        # gerak > ini*diag dari anchor = BERGERAK -> reset dwell
    box_ema: float = 0.4          # smoothing bbox slot
    id_bridge_s: float = 2.0      # ganti track-id di titik sama & <= ini = ID-switch mobil SAMA
    id_move_frac: float = 0.2     # ID-switch dianggap mobil sama bila geser <= ini*diag
    grace_s: float = 40.0         # slot tak terlihat > ini = kendaraan PERGI -> tutup sesi


def _point_in_poly(x, y, poly):
    """Ray casting; poly = list [(x,y),...] koordinat piksel."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi):
            inside = not inside
        j = i
    return inside


def _iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / ua if ua > 0 else 0.0


class ParkingTracker:
    """Stateful per kamera. update() dipanggil tiap frame yg diinferensi."""

    def __init__(self, params=None):
        self.p = params or ParkingParams()
        self.slots = []
        self.last_step = None

    def _close(self, s, events):
        if s.get("violated"):
            events.append({
                "kind": "clear", "uid": s["uid"], "sid": s.get("sid"),
                "tid": s.get("tid"), "vtype": s.get("vtype"),
                "dwell": s["last_seen"] - s["enter"],
                "box": (s["x1"], s["y1"], s["x2"], s["y2"]),
            })
        s["violated"] = False
        s["sid"] = None

    def attach_snapshot(self, uid, sid):
        for s in self.slots:
            if s["uid"] == uid:
                s["sid"] = sid
                return

    def active_violations(self, now):
        out = []
        for s in self.slots:
            if s.get("violated"):
                out.append({"uid": s["uid"], "sid": s.get("sid"), "tid": s.get("tid"),
                            "vtype": s.get("vtype"), "dwell": now - s["enter"],
                            "box": (s["x1"], s["y1"], s["x2"], s["y2"])})
        return out

    def update(self, now, detections, poly, dwell_limit):
        """detections: list (track_id, x1, y1, x2, y2, vtype). poly: list[(x,y)] atau None.
        Return (boxes, events). boxes=[(x1,y1,x2,y2,state,vtype,illegal)]; events start/clear."""
        p = self.p
        events, boxes = [], []

        prev = self.last_step
        if prev is not None:
            gap = now - prev
            if gap > p.freeze_gap_s:                 # freeze/stall -> geser waktu, tak dihitung
                for s in self.slots:
                    s["enter"] += gap
                    s["last_seen"] = s.get("last_seen", now) + gap
        self.last_step = now

        used = set()
        for (tid, x1, y1, x2, y2, vtype) in detections:
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            refx, refy = (x1 + x2) / 2.0, float(y2)      # tengah-bawah = titik roda
            inside = poly is not None and _point_in_poly(refx, refy, poly)
            if not inside:
                boxes.append((f"t{tid}", x1, y1, x2, y2, "outside", vtype, False, 0.0))
                continue
            diag = max(x2 - x1, y2 - y1, 1)
            best, best_score = None, 0.0
            for s in self.slots:
                if s["uid"] in used:
                    continue
                scx, scy = (s["x1"] + s["x2"]) / 2.0, (s["y1"] + s["y2"]) / 2.0
                dist = ((cx - scx) ** 2 + (cy - scy) ** 2) ** 0.5
                thr = p.match_dist * max(diag, s["x2"] - s["x1"], s["y2"] - s["y1"])
                iou = _iou((x1, y1, x2, y2), (s["x1"], s["y1"], s["x2"], s["y2"]))
                if dist <= thr or iou >= p.match_iou:
                    score = iou + (1.0 - min(dist / max(thr, 1.0), 1.0))
                    if score > best_score:
                        best, best_score = s, score

            if best is None:
                best = {"uid": uuid.uuid4().hex[:12], "enter": now, "sid": None,
                        "violated": False, "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                        "ax": cx, "ay": cy, "tid": tid}
                self.slots.append(best)
            else:
                dmove = ((cx - best["ax"]) ** 2 + (cy - best["ay"]) ** 2) ** 0.5
                gap_since = now - best.get("last_seen", now)
                same_track = (tid == best.get("tid"))
                # ANTI-AKUMULASI LINTAS-KENDARAAN: sesi diikat ke track-id. Kendaraan
                # LAIN (track-id beda) yg berhenti di titik sama = sesi BARU, BUKAN warisan
                # timer. Pengecualian: track-id berganti TAPI muncul lagi cepat (<= id_bridge_s,
                # deteksi ~kontinu) di posisi ~sama = ID-switch mobil DIAM yg sama -> lanjut.
                id_switch_same = (not same_track and gap_since <= p.id_bridge_s
                                  and dmove <= p.id_move_frac * diag)
                moved = same_track and dmove > p.move_frac * diag   # mobil sama menjauh = lewat
                new_vehicle = (not same_track) and (not id_switch_same)
                if moved or new_vehicle:
                    self._close(best, events)
                    best["enter"] = now
                    best["ax"], best["ay"] = cx, cy
                a = p.box_ema
                best["x1"] = a * x1 + (1 - a) * best["x1"]
                best["y1"] = a * y1 + (1 - a) * best["y1"]
                best["x2"] = a * x2 + (1 - a) * best["x2"]
                best["y2"] = a * y2 + (1 - a) * best["y2"]
            used.add(best["uid"])
            best.update({"tid": tid, "vtype": vtype, "last_seen": now})
            secs = now - best["enter"]
            illegal = secs >= dwell_limit
            if illegal and not best["violated"]:
                best["violated"] = True
                best["sid"] = None
                events.append({"kind": "start", "uid": best["uid"], "tid": tid,
                               "vtype": vtype, "dwell": secs,
                               "box": (best["x1"], best["y1"], best["x2"], best["y2"])})
            boxes.append((best["uid"], x1, y1, x2, y2,
                          "illegal" if illegal else "inside", vtype, illegal, secs))

        for s in [s for s in self.slots if now - s.get("last_seen", now) > p.grace_s]:
            self._close(s, events)
            self.slots.remove(s)
        return boxes, events
