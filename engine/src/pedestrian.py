"""Pipeline Pedestrian — deteksi orang + tracking + Face Recognition, live & mulus.

Per kamera (pola test.py: reader+buffer+pusher):
- tracking orang  : YOLO person.pt .track() (BoT-SORT) tiap frame -> ID stabil.
- Face Recognition : tiap FR_EVERY frame, deteksi wajah -> cocokkan ke galeri ->
                     tempel identitas/gender/usia ke track yang memuat wajah itu.
- Re-ID lintas-kamera: identitas wajah yang sama dikenali di kamera mana pun.
Video teranotasi (box + nama) di-push ke stream_server; event ke MQTT (throttled).
"""
import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np

_WIB = timezone(timedelta(hours=7))

from . import config, stream_server, fr_state, snapshots, gpu, token_refresh, infer_worker
from . import attributes as attr
from .grabber import LatestFrame
from .boxsync import BoxHistory
from .fr import FaceEngine
from .gallery import Gallery
from .envelope import build_envelope
from .yolo_util import norm_bbox

log = logging.getLogger("engine.pedestrian")


# Atribut ringkas (Indonesia) utk MQTT/DB + dashboard. age dipisah dari distribusi.
def _attrs_dict(info):
    a = {}
    g = info.get("gender")
    if g:
        a["gender"] = "pria" if g == "L" else "wanita"
    # Estimasi UMUR DIMATIKAN: genderage antelopev2 tak reliable di wajah CCTV
    # (anak kecil sering ditebak dewasa 20-30an). Lebih baik tak tampil drpd salah.
    if info.get("upperColor"):
        a["upperColor"] = info["upperColor"]
    if info.get("lowerColor"):
        a["lowerColor"] = info["lowerColor"]
    for acc in info.get("accessories", []):
        a[acc] = True                         # 'topi' | 'tas' | 'masker'
    return a


def _draw_scene(frame, bbox, label, known):
    """Frame PANORAMA penuh + bounding box orang (utk PAR): tak burik walau objek
    jauh, konteks lokasi tetap terlihat. Warna hijau=dikenali, kuning=belum."""
    img = frame.copy()
    x1, y1, x2, y2 = [int(v) for v in bbox]
    color = (80, 220, 120) if known else (80, 200, 255)
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
    if label:
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        ly = max(0, y1 - th - 8)
        cv2.rectangle(img, (x1, ly), (x1 + tw + 8, ly + th + 8), color, -1)
        cv2.putText(img, label, (x1 + 4, ly + th + 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 2, cv2.LINE_AA)
    return img


def _commit_snapshot(cam, body, fr, gallery, track_info, tid, scene=None, bbox=None):
    """Snapshot HANYA bila WAJAH terdeteksi (ala oss_vision): orang yang membelakangi
    kamera tidak disimpan. Simpan foto PANORAMA (frame penuh + box) + crop tubuh + wajah."""
    if fr.app is None or body is None or not body.size:
        return
    ff = fr.analyze(body)
    if not ff:
        return                                # wajah tak terlihat (membelakangi) -> SKIP
    f0 = max(ff, key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))
    fb = f0["bbox"]
    fx1, fy1 = max(0, fb[0]), max(0, fb[1])
    fx2, fy2 = min(body.shape[1], fb[2]), min(body.shape[0], fb[3])
    if fx2 <= fx1 or fy2 <= fy1:
        return                                # crop wajah tak valid -> SKIP
    face_img = body[fy1:fy2, fx1:fx2].copy()
    emb = f0["embedding"]
    nm, sc = gallery.match(emb)
    meta = {"trackId": int(tid), "gender": f0["gender"],
            "name": nm, "score": round(sc, 3)}
    if nm:
        track_info[tid] = {"name": nm, "score": sc, "gender": f0["gender"]}
    elif tid not in track_info:
        track_info[tid] = {"gender": f0["gender"]}
    # IDENTITAS GLOBAL + JEJAK lintas-kamera (anti-dobel: is_new False -> sudah ada foto).
    ts_iso = datetime.now(_WIB).isoformat()
    gid, is_new = snapshots.register_sighting(cam, emb, body, ts_iso)
    if not is_new:
        return
    meta["gid"] = gid                         # identitas global -> kunci jejak lintas-kamera
    # bawa atribut PAR teragregasi (warna baju, aksesori, age group) ke snapshot
    info = track_info.get(tid, {})
    meta["upperColor"] = info.get("upperColor")
    meta["lowerColor"] = info.get("lowerColor")
    meta["accessories"] = list(info.get("accessories", []))
    # foto PANORAMA: frame penuh + bounding box + label PAR (anti-burik saat objek jauh)
    scene_img = None
    if scene is not None and getattr(scene, "size", 0) and bbox is not None:
        if nm:
            label = f"{nm} {sc:.2f}"
        else:
            parts = [f"#{tid}"]
            if info.get("gender"):
                parts.append(info["gender"])
            if info.get("upperColor"):
                parts.append(info["upperColor"])
            label = " ".join(parts)
        scene_img = _draw_scene(scene, bbox, label, bool(nm))
    snapshots.add(cam, body, face_img, meta, scene_img=scene_img)


def _run_camera(cam, fr, gallery, mqtt_io):
    from ultralytics import YOLO
    model = YOLO(config.PERSON_MODEL)            # instance per kamera -> tracking independen
    src = config.live_playlist_url(cam)
    track_info = {}                              # track_id -> {name,score,gender,age,ageGroup,upperColor,lowerColor,accessories,parScore}
    snapped = {}                                 # track_id -> ts (sudah di-snapshot ke galeri)
    pending = {}                                 # track_id -> kandidat snapshot tertajam
    attr_samples = {}                            # track_id -> akumulasi sample atribut (PAR)
    attr_last = {}                               # track_id -> frame_i terakhir ekstrak warna/aksesori
    hist = BoxHistory(maxlen=config.LIVE_BUFFER + 25)  # box ber-seq -> sinkron+interpolasi; maxlen jangkau delay buffer
    trails = {}                                  # track_id -> deque titik kaki (trajectory)
    disp = {"count": 0, "trails": {}}            # jumlah orang + jejak lintasan (utk overlay)

    grab = LatestFrame(src, f"ped-{cam}", on_reconnect=token_refresh.refresh,
                       buffer=config.LIVE_BUFFER, skip_frozen=config.PED_SKIP_FROZEN).start()

    state = {"frame_i": 0, "last_emit": 0.0}

    def step(frame, seq):                      # 1 frame, dipanggil worker inferensi tunggal
        state["frame_i"] += 1
        fr_state.set_raw(cam, frame)          # frame mentah utk enrollment capture

        # --- tracking orang ---
        with gpu.lock:
            res = model.track(frame, persist=True, classes=[0], conf=config.PED_CONF,
                              device=0, imgsz=config.INFER_IMGSZ, half=config.INFER_HALF,
                              tracker=config.TRACKER_CFG, verbose=False)[0]
        persons = []
        if res.boxes is not None and res.boxes.id is not None:
            xyxy = res.boxes.xyxy.cpu().numpy()
            ids = res.boxes.id.cpu().numpy().astype(int)
            for b, tid in zip(xyxy, ids):
                persons.append((int(tid), int(b[0]), int(b[1]), int(b[2]), int(b[3])))

        # --- Face Recognition (throttled): nama (galeri) + umpan gender/usia/masker
        #     ke agregator atribut (PAR). 1x analyze per-frame, tanpa beban GPU ekstra. ---
        if fr.app is not None and state["frame_i"] % config.FR_EVERY == 0 and persons:
            for face in fr.analyze(frame):
                fb = face["bbox"]
                fx, fy = (fb[0] + fb[2]) // 2, (fb[1] + fb[3]) // 2
                for (tid, x1, y1, x2, y2) in persons:
                    if x1 <= fx <= x2 and y1 <= fy <= y2:    # wajah di dalam orang ini
                        name, score = gallery.match(face["embedding"])
                        info = track_info.setdefault(tid, {})
                        if name:
                            info["name"], info["score"] = name, score
                        s = attr.PersonAttributeSnapshot(
                            gender=face["gender"], age_estimate=None,  # umur dimatikan (tak reliable)
                            accessories=["masker"] if face.get("mask") else [])
                        attr.merge_attribute_samples(attr_samples.setdefault(tid, {}), s)
                        break

        # --- snapshot galeri: simpan frame TERTAJAM dari N frame pertama tiap orang ---
        h, w = frame.shape[:2]
        cur_ids = set()
        for (tid, x1, y1, x2, y2) in persons:
            cur_ids.add(tid)
            if tid in snapped:
                continue
            if (y2 - y1) < config.SNAP_MIN_H:          # terlalu kecil/jauh -> lewati (buram)
                continue
            # perlebar box: pulihkan KEPALA yg sering dipotong box YOLO (bahu ke atas)
            pbw, pbh = x2 - x1, y2 - y1
            bx1 = max(0, int(x1 - pbw * config.SNAP_PAD_X))
            by1 = max(0, int(y1 - pbh * config.SNAP_PAD_TOP))
            bx2 = min(w, int(x2 + pbw * config.SNAP_PAD_X))
            by2 = min(h, int(y2 + pbh * config.SNAP_PAD_BOT))
            body = frame[by1:by2, bx1:bx2]
            if body.size == 0:
                continue
            sharp = cv2.Laplacian(cv2.cvtColor(body, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
            st = pending.get(tid, {"sharp": -1.0, "tries": 0, "body": None,
                                   "frame": None, "bbox": None})
            st["tries"] += 1
            if sharp > st["sharp"]:                 # frame tertajam -> simpan crop + frame penuh + bbox
                st["sharp"], st["body"] = sharp, body.copy()
                st["frame"], st["bbox"] = frame.copy(), (bx1, by1, bx2, by2)
            pending[tid] = st
            if st["tries"] >= config.SNAP_TRIES or sharp >= config.SNAP_SHARP_OK:
                if st["sharp"] >= config.SNAP_MIN_SHARP:   # buang yang super-buram
                    _commit_snapshot(cam, st["body"], fr, gallery, track_info, tid,
                                     st["frame"], st["bbox"])
                snapped[tid] = time.time()
                pending.pop(tid, None)
        # orang sudah hilang tapi punya kandidat -> simpan yang terbaik (bila cukup tajam)
        for tid in [t for t in pending if t not in cur_ids]:
            st = pending.pop(tid)
            if st["body"] is not None and st["sharp"] >= config.SNAP_MIN_SHARP:
                _commit_snapshot(cam, st["body"], fr, gallery, track_info, tid,
                                 st["frame"], st["bbox"])

        # --- PAR: warna baju + aksesori (CPU) per track (throttled) -> agregasi
        #     jadi nilai stabil (modus/rata-rata) di track_info utk overlay+emit+snapshot ---
        if config.ATTR_ENABLED:
            for (tid, x1, y1, x2, y2) in persons:
                if state["frame_i"] - attr_last.get(tid, -10000) >= config.ATTR_EVERY:
                    attr_last[tid] = state["frame_i"]
                    s = attr.extract_attributes(frame, (x1, y1, x2, y2))
                    attr.merge_attribute_samples(attr_samples.setdefault(tid, {}), s)
                samples = attr_samples.get(tid)
                if samples:
                    summ = attr.summarize_attributes(samples, min_samples=1)
                    info = track_info.setdefault(tid, {})
                    info["gender"] = summ["gender"] or info.get("gender")
                    info["upperColor"] = summ["clothing_top_color"] or info.get("upperColor")
                    info["lowerColor"] = summ["clothing_bottom_color"] or info.get("lowerColor")
                    if summ["accessories"]:
                        info["accessories"] = summ["accessories"]
                    info["parScore"] = round(float(summ["gender_confidence"] or 0.0), 3)

        # --- siapkan box utk display (gambar dilakukan thread display) ---
        boxes = {}                               # tid -> (x1,y1,x2,y2,label,color) utk sinkron box
        for (tid, x1, y1, x2, y2) in persons:
            info = track_info.get(tid, {})
            if info.get("name"):                 # dikenali (galeri) -> hijau, tampil nama
                label = f"{info['name']} {info['score']:.2f}"
                color = (80, 220, 120)
            else:                                # belum dikenal -> kuning, tampil atribut PAR
                parts = [f"#{tid}"]
                if info.get("gender"):
                    parts.append(info["gender"])             # L / P
                if info.get("upperColor"):
                    parts.append(info["upperColor"])
                label = " ".join(parts)
                color = (80, 200, 255) if len(parts) > 1 else (200, 180, 80)
            boxes[tid] = (x1, y1, x2, y2, label, color)
        hist.put(seq, boxes)                     # simpan ber-seq utk sinkron ke frame display

        # --- TRAJECTORY: rekam titik kaki tiap orang -> jejak lintasan di video ---
        cur = set()
        for (tid, x1, y1, x2, y2) in persons:
            cur.add(tid)
            trails.setdefault(tid, deque(maxlen=config.TRAIL_LEN)).append(((x1 + x2) // 2, y2))
        for t in [t for t in trails if t not in cur]:   # orang hilang -> buang jejaknya
            trails.pop(t, None)
        disp["trails"] = {t: list(dq) for t, dq in trails.items()}
        disp["count"] = len(persons)

        # prune state track yang sudah lama hilang (cegah memori tumbuh tanpa batas)
        if len(attr_samples) > 600:
            live = {t for (t, *_r) in persons}
            for d in (attr_samples, attr_last, track_info, snapped):
                for tid in [k for k in d if k not in live]:
                    d.pop(tid, None)

        # --- emit event (throttled) ---
        now = time.time()
        if (mqtt_io is not None and not config.STREAM_ONLY
                and now - state["last_emit"] >= config.LIVE_EVENT_INTERVAL):
            state["last_emit"] = now
            for (tid, x1, y1, x2, y2) in persons:
                info = track_info.get(tid, {})
                data = {
                    "trackId": int(tid),
                    "name": info.get("name"),
                    "attributes": _attrs_dict(info),       # PAR: gender,age,ageGroup,warna,aksesori
                    "bbox": norm_bbox([x1, y1, x2, y2], w, h),
                    "parScore": info.get("parScore"),
                    "reidScore": round(float(info.get("score", 0.0)), 3),
                }
                mqtt_io.publish_event(build_envelope(
                    cam, "pedestrian", "track", data, info.get("score")))

    infer_worker.register(cam, grab, step, f"ped {cam}")

    # DISPLAY: video MULUS @ LIVE_FPS — kuras buffer playout FIFO pada laju stabil
    # (serap burst HLS) + box hasil inferensi terakhir. fps inferensi (berat krn FR)
    # tak membatasi kemulusan video. Prebuffer dulu biar jitter terserap.
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
            # TRAJECTORY: jejak lintasan tiap orang (garis kuning + titik kaki)
            for pts in disp.get("trails", {}).values():
                if len(pts) >= 2:
                    cv2.polylines(img, [np.array(pts, np.int32)], False, (40, 200, 255), 2, cv2.LINE_AA)
                    cv2.circle(img, tuple(pts[-1]), 4, (40, 200, 255), -1, cv2.LINE_AA)
            # box disinkron+interpolasi ke frame seq ini -> menempel & mulus
            for (x1, y1, x2, y2, label, color) in hist.at(last_seq):
                cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
                cv2.putText(img, label, (x1, max(y1 - 6, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            cv2.putText(img, f"ORANG: {disp['count']}", (12, img.shape[0] - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)
            stream_server.publish_frame(cam, img)
        nxt += interval
        d = nxt - time.time()
        time.sleep(d if d > 0 else 0.003)     # lantai: jangan spin (sisakan CPU utk inferensi)


def start(mqtt_io=None):
    if not config.LIVE_ENABLED or not config.PED_CAMERAS:
        return
    fr_state.face_engine = FaceEngine()
    if not fr_state.face_engine.load():
        log.warning("FaceEngine gagal — pedestrian jalan tanpa FR (tracking saja)")
    fr_state.gallery = Gallery(fr_state.face_engine)
    fr_state.gallery.build()
    for cam in config.PED_CAMERAS:
        threading.Thread(target=_run_camera,
                         args=(cam, fr_state.face_engine, fr_state.gallery, mqtt_io),
                         daemon=True, name=f"ped-push-{cam}").start()
        log.info("Pedestrian pipeline mulai: %s", cam)
        time.sleep(config.CAM_STAGGER_S)        # stagger startup
