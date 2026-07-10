"""Pipeline Parkir Liar — deteksi kendaraan + tracking + ROI dwell time.

Per kamera (pola test.py: reader+buffer+pusher):
- deteksi+track kendaraan (car/motor/bus/truck) YOLO .track() -> ID stabil.
- titik acuan kendaraan (tengah-bawah bbox) di dalam ROI? akumulasi durasi.
- durasi di ROI >= ambang (default 20 detik, diatur per-kamera dari dashboard) -> PARKIR LIAR.
- 1 SESI = 1 record (bukan periodik); difinalisasi saat kendaraan PERGI (start s/d pergi).

LOGIKA INTI dipindah ke park_logic.ParkingTracker (MURNI, tanpa YOLO/IO) supaya bisa
diuji unit di luar sistem (engine/tests/test_park_logic.py). Modul ini hanya menjembatani
YOLO -> tracker -> snapshot/MQTT/gambar. ROI digambar via dashboard (roi_store); tanpa ROI
(dan tanpa default PARKING_ZONES) hanya menampilkan kendaraan.
"""
import logging
import threading
import time

import cv2
import numpy as np

from . import config, stream_server, roi_store, gpu, token_refresh, snapshots, infer_worker
from . import park_logic
from .grabber import LatestFrame
from .boxsync import BoxHistory
from .envelope import build_envelope
from .yolo_util import norm_bbox

log = logging.getLogger("engine.parking")


def _fmt(sec):
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def _park_params():
    return park_logic.ParkingParams(
        freeze_gap_s=config.PARK_FREEZE_GAP_S, match_iou=config.PARK_MATCH_IOU,
        match_dist=config.PARK_MATCH_DIST, move_frac=config.PARK_MOVE_FRAC,
        box_ema=config.PARK_BOX_EMA, id_bridge_s=config.PARK_ID_BRIDGE_S,
        id_move_frac=config.PARK_ID_MOVE_FRAC, grace_s=config.PARK_GRACE_S)


def _run_camera(cam, mqtt_io):
    from ultralytics import YOLO
    model = YOLO(config.PERSON_MODEL)        # yolov8s COCO (punya kelas kendaraan)
    src = config.live_playlist_url(cam)
    tracker = park_logic.ParkingTracker(_park_params())    # occupancy per-slot + anti akumulasi lintas-kendaraan
    grab = LatestFrame(src, f"park-{cam}", on_reconnect=token_refresh.refresh,
                       buffer=config.LIVE_BUFFER, skip_frozen=config.PARK_SKIP_FROZEN).start()
    hist = BoxHistory(maxlen=config.LIVE_BUFFER + 25)
    emit_state = {"last_emit": 0.0}

    def _emit(ev, w, h, cleared=False):
        """ev: {sid, tid, vtype, dwell, box=(x1,y1,x2,y2)}. Publish event pelanggaran."""
        if mqtt_io is None or config.STREAM_ONLY:
            return
        data = {
            "violationId": ev.get("sid"), "trackId": int(ev.get("tid") or 0),
            "vehicleType": ev.get("vtype"), "dwellSeconds": int(ev.get("dwell") or 0),
            "zoneName": "ROI", "bbox": norm_bbox(list(ev["box"]), w, h),
            "snapshotId": ev.get("sid"),
        }
        if cleared:
            data["status"] = "cleared"
        mqtt_io.publish_event(build_envelope(cam, "parking", "violation", data, 0.9))

    def step(frame, seq):                      # 1 frame, dipanggil worker inferensi tunggal
        h, w = frame.shape[:2]
        with gpu.lock:
            res = model.track(frame, persist=True, classes=config.PARK_CLASSES,
                              conf=config.PARK_CONF, device=0,
                              imgsz=config.PARK_INFER_IMGSZ, half=config.INFER_HALF,
                              tracker=config.TRACKER_CFG, verbose=False)[0]
        detections = []
        if res.boxes is not None and res.boxes.id is not None:
            xyxy = res.boxes.xyxy.cpu().numpy()
            ids = res.boxes.id.cpu().numpy().astype(int)
            cls = res.boxes.cls.cpu().numpy().astype(int)
            for b, tid, c in zip(xyxy, ids, cls):
                name = model.names.get(int(c), "kendaraan")
                detections.append((int(tid), int(b[0]), int(b[1]), int(b[2]), int(b[3]), name))

        roi = roi_store.get(cam)
        poly = [[x * w, y * h] for x, y in roi] if roi else None
        dwell_limit = roi_store.get_dwell(cam) or config.PARK_DWELL_S

        now = time.time()
        boxes_list, events = tracker.update(now, detections, poly, dwell_limit)

        for e in events:
            if e["kind"] == "start":           # pertama tembus ambang -> snapshot SEKALI
                x1, y1, x2, y2 = [int(v) for v in e["box"]]
                crop = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
                sid = None
                if crop.size:
                    sid = snapshots.add_parking(cam, crop.copy(), {
                        "trackId": int(e["tid"]), "vehicleType": e["vtype"],
                        "dwellSeconds": int(e["dwell"])})
                sid = sid or e["uid"]
                tracker.attach_snapshot(e["uid"], sid)
                _emit({"sid": sid, "tid": e["tid"], "vtype": e["vtype"],
                       "dwell": e["dwell"], "box": e["box"]}, w, h)
            elif e["kind"] == "clear":         # kendaraan PERGI -> finalisasi durasi + cleared
                if e.get("sid"):
                    snapshots.update_parking(e["sid"], dwell_seconds=int(e["dwell"]),
                                             departed=True)
                _emit(e, w, h, cleared=True)

        # gambar box (posisi deteksi MENTAH -> menempel ke kendaraan; key stabil utk interpolasi)
        boxes = {}
        for (key, x1, y1, x2, y2, st, vtype, illegal, secs) in boxes_list:
            if st == "outside":
                color, label = (120, 200, 120), vtype
            elif illegal:
                color, label = (0, 0, 255), f"PARKIR LIAR {_fmt(secs)}"
            else:
                color, label = (0, 200, 255), f"{vtype} {_fmt(secs)}"
            boxes[key] = (x1, y1, x2, y2, color, label)
        hist.put(seq, boxes)

        # HEARTBEAT (throttled) — UPSERT 1 baris/sesi (durasi live + "aktif").
        if now - emit_state["last_emit"] >= config.LIVE_EVENT_INTERVAL:
            emit_state["last_emit"] = now
            for v in tracker.active_violations(now):
                _emit(v, w, h)

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
