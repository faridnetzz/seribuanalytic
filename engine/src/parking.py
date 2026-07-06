"""Pipeline Parkir Liar — deteksi kendaraan + tracking + ROI dwell time.

Per kamera (pola test.py: reader+buffer+pusher):
- deteksi+track kendaraan (car/motor/bus/truck) YOLO .track() -> ID stabil.
- titik acuan kendaraan (tengah-bawah bbox) di dalam ROI? akumulasi durasi.
- durasi di ROI >= ambang (default 20 detik, diatur per-kamera dari dashboard) -> PARKIR LIAR.
- 1 SESI = 1 record (bukan periodik); difinalisasi saat kendaraan PERGI (start s/d pergi).
  Grace (PARK_GRACE_S) menyerap kedipan deteksi agar sesi tak terpecah jadi banyak record.
ROI digambar via dashboard (roi_store). Tanpa ROI: hanya tampilkan kendaraan.
"""
import logging
import threading
import time
import uuid

import cv2
import numpy as np

from . import config, stream_server, roi_store, gpu, token_refresh, snapshots, infer_worker
from .grabber import LatestFrame
from .boxsync import BoxHistory
from .envelope import build_envelope
from .yolo_util import norm_bbox

log = logging.getLogger("engine.parking")


def _fmt(sec):
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def _iou(a, b):
    """IoU 2 bbox (x1,y1,x2,y2). Utk cocokkan deteksi ke 'slot parkir' by LOKASI."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _run_camera(cam, mqtt_io):
    from ultralytics import YOLO
    model = YOLO(config.PERSON_MODEL)        # yolov8s COCO (punya kelas kendaraan)
    src = config.live_playlist_url(cam)
    # OCCUPANCY SPASIAL (bukan track ID!) — kunci anti double-record. Tiap "slot"
    # = lokasi parkir (bbox). Deteksi dicocokkan ke slot terdekat by IoU. Mobil diam
    # di titik sama = 1 slot = 1 sesi, terus dihitung sampai BENAR-BENAR tak ada
    # kendaraan di titik itu > grace — walau track ID berganti / deteksi kedip / stream
    # putus. Jadi parkir TAK reset walau bounding box lepas sesaat.
    slots = []        # [{uid,x1,y1,x2,y2,tid,enter,last_seen,vtype,sid,violated}]
    grab = LatestFrame(src, f"park-{cam}", on_reconnect=token_refresh.refresh,
                       buffer=config.LIVE_BUFFER, skip_frozen=config.PARK_SKIP_FROZEN).start()
    # maxlen menjangkau seluruh delay buffer playout (LIVE_BUFFER frame) -> box utk
    # frame yg ditampilkan (delay ~5dtk) tak jatuh keluar riwayat -> box tak basi/lepas.
    hist = BoxHistory(maxlen=config.LIVE_BUFFER + 25)
    state = {"last_emit": 0.0, "last_step": None}

    def _emit(s, now, w, h, cleared=False):
        if mqtt_io is None or config.STREAM_ONLY:
            return
        total = int((s["last_seen"] if cleared else now) - s["enter"])
        data = {
            "violationId": s["sid"], "trackId": int(s.get("tid", 0)),
            "vehicleType": s["vtype"], "dwellSeconds": total, "zoneName": "ROI",
            "bbox": norm_bbox([s["x1"], s["y1"], s["x2"], s["y2"]], w, h),
            "snapshotId": s["sid"],
        }
        if cleared:
            data["status"] = "cleared"
        mqtt_io.publish_event(build_envelope(cam, "parking", "violation", data, 0.9))

    def _close(s, now, w, h):
        """Akhiri sesi parkir slot (bila sempat melanggar): finalisasi durasi total +
        emit cleared. Dipanggil saat kendaraan PERGI (grace) atau BERGERAK (bukan parkir)."""
        if s.get("violated"):
            snapshots.update_parking(s["sid"], dwell_seconds=int(s["last_seen"] - s["enter"]),
                                     departed=True)
            _emit(s, now, w, h, cleared=True)
        s["violated"] = False
        s["sid"] = None

    def step(frame, seq):                      # 1 frame, dipanggil worker inferensi tunggal
        h, w = frame.shape[:2]
        with gpu.lock:
            res = model.track(frame, persist=True, classes=config.PARK_CLASSES,
                              conf=config.PARK_CONF, device=0,
                              imgsz=config.PARK_INFER_IMGSZ, half=config.INFER_HALF,
                              tracker=config.TRACKER_CFG, verbose=False)[0]
        vehicles = []
        if res.boxes is not None and res.boxes.id is not None:
            xyxy = res.boxes.xyxy.cpu().numpy()
            ids = res.boxes.id.cpu().numpy().astype(int)
            cls = res.boxes.cls.cpu().numpy().astype(int)
            for b, tid, c in zip(xyxy, ids, cls):
                vehicles.append((int(tid), int(b[0]), int(b[1]), int(b[2]), int(b[3]), int(c)))

        roi = roi_store.get(cam)
        poly = np.array([[int(x * w), int(y * h)] for x, y in roi], np.int32) if roi else None
        dwell_limit = roi_store.get_dwell(cam) or config.PARK_DWELL_S

        now = time.time()
        # GUARD FREEZE/STALL: bila ada JEDA observasi (stream freeze -> frame beku dibuang
        # grabber, atau stream putus/reconnect), jam dinding tetap jalan padahal kendaraan
        # TAK teramati. Tanpa ini seluruh durasi freeze terhitung sbg dwell -> PARKIR LIAR
        # palsu utk kendaraan yg sebenarnya LEWAT. Solusi: jeda > ambang -> geser enter &
        # last_seen tiap slot sebesar jeda -> interval tak teramati TAK dihitung dwell/grace.
        prev = state["last_step"]
        if prev is not None:
            gap = now - prev
            if gap > config.PARK_FREEZE_GAP_S:
                log.warning("[%s] jeda observasi %.1fs (freeze/stall) -> dwell tak dihitung", cam, gap)
                for s in slots:
                    s["enter"] += gap
                    s["last_seen"] = s.get("last_seen", now) + gap
        state["last_step"] = now
        boxes = {}
        used = set()                              # slot yang sudah dipakai frame ini (1 slot : 1 kendaraan)
        for (tid, x1, y1, x2, y2, c) in vehicles:
            name = model.names.get(c, "kendaraan")
            ref = ((x1 + x2) // 2, y2)            # tengah-bawah = titik roda
            inside = poly is not None and cv2.pointPolygonTest(poly, ref, False) >= 0
            if not inside:                        # kendaraan lewat / di luar zona
                boxes[f"t{tid}"] = (x1, y1, x2, y2, (120, 200, 120), name)
                continue
            # cocokkan ke SLOT by JARAK-PUSAT (tahan jitter ukuran bbox) ATAU IoU
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            diag = max(x2 - x1, y2 - y1, 1)
            best, best_score = None, 0.0
            for s in slots:
                if s["uid"] in used:
                    continue
                scx, scy = (s["x1"] + s["x2"]) / 2.0, (s["y1"] + s["y2"]) / 2.0
                dist = ((cx - scx) ** 2 + (cy - scy) ** 2) ** 0.5
                thr = config.PARK_MATCH_DIST * max(diag, s["x2"] - s["x1"], s["y2"] - s["y1"])
                iou = _iou((x1, y1, x2, y2), (s["x1"], s["y1"], s["x2"], s["y2"]))
                if dist <= thr or iou >= config.PARK_MATCH_IOU:
                    score = iou + (1.0 - min(dist / max(thr, 1.0), 1.0))
                    if score > best_score:
                        best, best_score = s, score
            if best is None:                      # lokasi baru -> sesi parkir baru
                best = {"uid": uuid.uuid4().hex[:12], "enter": now, "sid": None,
                        "violated": False, "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                        "ax": cx, "ay": cy, "ids": {tid: now}}  # anchor=posisi mulai diam; ids=penghuni
                slots.append(best)
            else:
                dmove = ((cx - best["ax"]) ** 2 + (cy - best["ay"]) ** 2) ** 0.5
                # KONTINUITAS IDENTITAS: ID track penghuni slot berganti ke ID yg tak
                # baru-baru ini menempati slot ini = KENDARAAN LAIN (lalu lintas), bukan
                # mobil yg sama parkir. (Mobil parkir diam -> ID BoT-SORT stabil.)
                seen = {i: t for i, t in best.get("ids", {}).items()
                        if now - t <= config.PARK_ID_MEMORY_S}
                other_vehicle = bool(seen) and tid not in seen
                seen[tid] = now
                best["ids"] = seen
                # GERBANG RESET: kendaraan BERGERAK menjauh dari anchor (lewat), ATAU
                # penghuni jadi kendaraan LAIN yg posisinya bergeser dari anchor (handoff
                # lalu lintas) -> akhiri sesi & RESET dwell+anchor. ID berganti TAPI posisi
                # persis sama = ID-switch mobil yg sama (parkir) -> JANGAN reset.
                moved = dmove > config.PARK_MOVE_FRAC * diag
                handoff = other_vehicle and dmove > config.PARK_ID_MOVE_FRAC * diag
                if moved or handoff:
                    _close(best, now, w, h)
                    best["enter"] = now
                    best["ax"], best["ay"] = cx, cy
                    best["ids"] = {tid: now}
                a = config.PARK_BOX_EMA           # EMA bbox -> box stabil (tak lepas/jitter)
                best["x1"] = int(a * x1 + (1 - a) * best["x1"])
                best["y1"] = int(a * y1 + (1 - a) * best["y1"])
                best["x2"] = int(a * x2 + (1 - a) * best["x2"])
                best["y2"] = int(a * y2 + (1 - a) * best["y2"])
            used.add(best["uid"])
            best.update({"tid": tid, "vtype": name, "last_seen": now})
            secs = now - best["enter"]
            illegal = secs >= dwell_limit
            bx1, by1, bx2, by2 = best["x1"], best["y1"], best["x2"], best["y2"]
            # snapshot SEKALI per sesi saat pertama tembus ambang
            if illegal and not best["violated"]:
                crop = frame[max(0, by1):min(h, by2), max(0, bx1):min(w, bx2)]
                sid = None
                if crop.size:
                    sid = snapshots.add_parking(cam, crop.copy(), {
                        "trackId": int(tid), "vehicleType": name,
                        "dwellSeconds": int(secs)})
                best["sid"] = sid or best["uid"]
                best["violated"] = True
            if illegal:
                color, label = (0, 0, 255), f"PARKIR LIAR {_fmt(secs)}"
            else:
                color, label = (0, 200, 255), f"{name} {_fmt(secs)}"
            # Tampilkan box MENTAH (posisi deteksi asli) -> menempel ke kendaraan
            # BERGERAK; interpolasi BoxHistory yg meratakan antar-frame. (EMA best["x*"]
            # tetap utk matching/crop; EMA bikin box telat di objek bergerak -> "lepas".)
            boxes[best["uid"]] = (x1, y1, x2, y2, color, label)
        hist.put(seq, boxes)

        # FINALISASI: slot tak terisi > grace -> kendaraan PERGI -> tutup record (durasi
        # total mulai-diam s/d pergi). Grace besar menyerap kedipan/stream putus.
        for s in [s for s in slots if now - s["last_seen"] > config.PARK_GRACE_S]:
            _close(s, now, w, h)
            slots.remove(s)

        # HEARTBEAT (throttled) — UPSERT 1 baris/sesi (durasi live + "aktif"); BUKAN record baru.
        if now - state["last_emit"] >= config.LIVE_EVENT_INTERVAL:
            state["last_emit"] = now
            for s in slots:
                if s["violated"]:
                    _emit(s, now, w, h)

    infer_worker.register(cam, grab, step, f"park {cam}", priority=config.PARK_INFER_PRIORITY)

    # DISPLAY: video MULUS @ LIVE_FPS — kuras buffer playout FIFO pada laju stabil
    # (serap burst HLS) + ROI + box cached. Prebuffer dulu biar jitter terserap.
    interval = 1.0 / config.LIVE_FPS
    while grab.buffered() < config.LIVE_PREBUFFER:
        time.sleep(0.05)
    nxt = time.time()
    last, last_seq = None, 0
    while True:
        dseq, frame = grab.pop_display()
        if frame is not None:
            last, last_seq = frame, dseq
        if last is not None:
            img = last.copy()
            h, w = img.shape[:2]
            roi = roi_store.get(cam)
            if roi:
                poly = np.array([[int(x * w), int(y * h)] for x, y in roi], np.int32)
                cv2.polylines(img, [poly], True, (255, 200, 40), 2)
            else:
                cv2.putText(img, "ROI belum digambar", (12, 28),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (40, 200, 255), 2)
            # box disinkron+interpolasi ke frame seq ini -> menempel & mulus
            for (x1, y1, x2, y2, color, label) in hist.at(last_seq):
                cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
                cv2.putText(img, label, (x1, max(y1 - 6, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            stream_server.publish_frame(cam, img)
        nxt += interval
        d = nxt - time.time()
        time.sleep(d if d > 0 else 0.003)     # lantai: jangan spin (sisakan CPU utk inferensi)


def start(mqtt_io=None):
    if not config.LIVE_ENABLED or not config.PARK_CAMERAS:
        return
    for cam in config.PARK_CAMERAS:
        threading.Thread(target=_run_camera, args=(cam, mqtt_io),
                         daemon=True, name=f"park-push-{cam}").start()
        log.info("Parking pipeline mulai: %s (dwell %ds)", cam, int(config.PARK_DWELL_S))
        time.sleep(config.CAM_STAGGER_S)        # stagger startup
