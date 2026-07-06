"""Streaming live MULUS + deteksi — pola sama persis test.py.

Per kamera live:
- reader thread : decode HLS (via proxy internal) + YOLO -> frame teranotasi -> buffer.
- pusher loop   : pop buffer pada laju stabil (LIVE_FPS) -> stream_server.
Pemisahan ini yang bikin video dashboard tidak patah-patah (jaringan bursty
di batas segmen HLS diserap buffer).
"""
import logging
import threading
import time
import uuid

import cv2

from . import config, stream_server, gpu, token_refresh, infer_worker, snapshots
from .grabber import LatestFrame
from .boxsync import BoxHistory
from .yolo_util import load_yolo, norm_bbox
from .envelope import build_envelope

log = logging.getLogger("engine.live")


def _severity(area_ratio):
    if area_ratio >= 0.15:
        return "critical"
    if area_ratio >= 0.08:
        return "high"
    if area_ratio >= 0.03:
        return "medium"
    return "low"


def _fmt(sec):
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def _iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _run_camera(cam_id, src, model, mqtt_io):
    grab = LatestFrame(src, f"live-{cam_id}", on_reconnect=token_refresh.refresh,
                       buffer=config.LIVE_BUFFER).start()
    hist = BoxHistory(maxlen=config.LIVE_BUFFER + 25)  # box ber-seq -> sinkron; maxlen jangkau delay buffer
    # OCCUPANCY TUMPUKAN (seperti slot parkir): 1 pile = 1 episode dari muncul s/d
    # diangkut. Dicocokkan by LOKASI (IoU) -> tahan kedip; durasi = persistensi.
    piles = []        # {uid,x1,y1,x2,y2,fw,fh,enter,last_seen,peak_area,emitted}
    state = {"last_emit": 0.0}

    def _emit_pile(p, now, cleared=False):
        if mqtt_io is None or config.STREAM_ONLY:
            return
        et = "cleared" if cleared else ("update" if p.get("emitted") else "detection")
        data = {
            "pileUid": p["uid"], "severity": _severity(p["peak_area"]),
            "areaRatio": round(p["peak_area"], 4), "snapshotId": p["uid"],
            "bbox": norm_bbox([p["x1"], p["y1"], p["x2"], p["y2"]], p["fw"], p["fh"]),
            "durationSeconds": int((p["last_seen"] if cleared else now) - p["enter"]),
            "isFloating": False,
        }
        if cleared:
            data["status"] = "cleared"
        mqtt_io.publish_event(build_envelope(cam_id, "waste", et, data, 0.9))
        p["emitted"] = True

    def step(frame, seq):                      # 1 frame, dipanggil worker inferensi tunggal
        h, w = frame.shape[:2]
        with gpu.lock:
            res = model(frame, conf=config.LIVE_CONF, device=0,
                        imgsz=config.WASTE_IMGSZ, half=config.INFER_HALF,
                        verbose=False)[0]
        # buang kotak RAKSASA skor-rendah (palsu) & noise mungil -> hanya tumpukan wajar
        dets = []
        for box in res.boxes:
            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
            area = ((x2 - x1) * (y2 - y1)) / float(w * h)
            if area > config.WASTE_MAX_AREA or area < config.WASTE_MIN_AREA:
                continue
            dets.append((x1, y1, x2, y2, area))

        now = time.time()
        boxes = {}
        used = set()
        for (x1, y1, x2, y2, area) in dets:
            # cocokkan ke TUMPUKAN (slot) by IoU -> sesi sama walau kedip/stream putus
            best, best_iou = None, config.WASTE_MATCH_IOU
            for p in piles:
                if p["uid"] in used:
                    continue
                i = _iou((x1, y1, x2, y2), (p["x1"], p["y1"], p["x2"], p["y2"]))
                if i >= best_iou:
                    best, best_iou = p, i
            if best is None:                   # tumpukan BARU -> snapshot sekali
                crop = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
                sid = (snapshots.add_waste(cam_id, crop.copy(),
                       {"severity": _severity(area), "areaRatio": round(area, 4),
                        "durationSeconds": 0}) if crop.size else uuid.uuid4().hex[:12])
                best = {"uid": sid, "enter": now, "peak_area": area, "emitted": False,
                        "x1": x1, "y1": y1, "x2": x2, "y2": y2}
                piles.append(best)
            else:
                best["x1"], best["y1"], best["x2"], best["y2"] = x1, y1, x2, y2
                best["peak_area"] = max(best["peak_area"], area)
            used.add(best["uid"])
            best["last_seen"] = now
            best["fw"], best["fh"] = w, h
            dur = int(now - best["enter"])
            label = f"Sampah {_severity(best['peak_area'])} {_fmt(dur)}"
            boxes[best["uid"]] = (x1, y1, x2, y2, label)
        hist.put(seq, boxes)

        # FINALISASI: tumpukan tak terlihat > grace -> DIANGKUT/hilang -> tutup episode.
        for p in [p for p in piles if now - p["last_seen"] > config.WASTE_GRACE_S]:
            p["fw"], p["fh"] = w, h
            _emit_pile(p, now, cleared=True)
            snapshots.update_waste(p["uid"], durationSeconds=int(p["last_seen"] - p["enter"]),
                                   status="cleared")
            piles.remove(p)

        # emit: tumpukan BARU langsung; sisanya heartbeat tiap WASTE_HEARTBEAT_S.
        due = now - state["last_emit"] >= config.WASTE_HEARTBEAT_S
        for p in piles:
            if not p.get("emitted") or due:
                _emit_pile(p, now)
        if due:
            state["last_emit"] = now

    # sampah = objek statis -> cukup infer tiap 2 dtk; sisakan GPU utk kamera tracking
    infer_worker.register(cam_id, grab, step, f"live {cam_id}", min_interval=2.0)

    # DISPLAY: video MULUS @ LIVE_FPS — kuras buffer playout FIFO pada laju stabil
    # (serap burst HLS) + box hasil inferensi terakhir. fps inferensi tak membatasi
    # kemulusan. Prebuffer dulu biar jitter terserap sejak frame pertama.
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
            # tumpukan statis -> box nearest ke frame seq ini (tanpa interpolasi)
            for (x1, y1, x2, y2, label) in hist.at(last_seq, interpolate=False):
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
                cv2.putText(img, label, (x1, max(y1 - 5, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            stream_server.publish_frame(cam_id, img)
        nxt += interval
        d = nxt - time.time()
        time.sleep(d if d > 0 else 0.003)     # lantai: jangan spin (sisakan CPU utk inferensi)


def start(mqtt_io=None):
    if not config.LIVE_ENABLED or not config.LIVE_STREAMS:
        return
    model = load_yolo(config.MODELS_DIR + "/waste.pt")
    if model is None:
        log.warning("waste.pt tak ada — live stream nonaktif")
        return
    for cam_id, src in config.LIVE_STREAMS.items():
        threading.Thread(target=_run_camera, args=(cam_id, src, model, mqtt_io),
                         daemon=True, name=f"live-push-{cam_id}").start()
        log.info("Live stream mulai: %s <- %s", cam_id, src)
        time.sleep(config.CAM_STAGGER_S)        # stagger: biar established dulu
