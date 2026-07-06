"""Base class worker modul.

Dua pola:
- FrameWorker      : menarik frame penuh via RTSP, jalankan model citra penuh.
- PerceptionWorker : mendengar metadata objek/track dari DeepStream (MQTT),
                     jalankan logika/model pada objek tersebut.

Setiap worker memuat model dari MODELS_DIR. Jika file model belum ada, worker
tetap hidup tetapi melewati inferensi (status 'degraded') sampai model tersedia
— sehingga engine bisa jalan walau sebagian model masih dikembangkan.
"""
import logging
import os
import threading
import time

from .. import config
from .. import stream_server
from ..envelope import build_envelope
from ..frame_source import FrameSource

log = logging.getLogger("engine.module")


class BaseWorker:
    code = "base"

    def __init__(self, mqtt_io):
        self.mqtt = mqtt_io
        self.ready = False
        self._stop = threading.Event()
        self._thread = None
        self.load_models(config.MODELS_DIR)

    # --- override di subclass ---
    def load_models(self, models_dir: str):
        """Muat model. Set self.ready=True jika berhasil."""
        raise NotImplementedError

    # --- util ---
    def _model_path(self, filename: str):
        path = os.path.join(config.MODELS_DIR, filename)
        if not os.path.exists(path):
            log.warning("[%s] model belum ada: %s (modul jalan degraded)",
                        self.code, path)
            return None
        return path

    def emit(self, camera_id, event_type, data, confidence=None):
        self.mqtt.publish_event(
            build_envelope(camera_id, self.code, event_type, data, confidence)
        )

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name=self.code)
        self._thread.start()
        log.info("[%s] worker mulai (ready=%s)", self.code, self.ready)

    def stop(self):
        self._stop.set()

    def _run(self):
        raise NotImplementedError


class FrameWorker(BaseWorker):
    """Loop ambil frame RTSP per kamera, jalankan infer()."""

    def __init__(self, mqtt_io):
        super().__init__(mqtt_io)
        # Lewati kamera yang ditangani live_stream (sumber HLS live, bukan rekaman).
        self.cameras = [c for c in config.cameras_for(self.code)
                        if c["id"] not in config.LIVE_STREAMS]
        # Sumber otomatis: file video uji bila tersedia, jika tidak RTSP.
        self.sources = {c["id"]: FrameSource(config.source_for(c["id"])) for c in self.cameras}

    def infer(self, camera_id, frame):
        """Override: kembalikan list (data_dict, confidence) atau []."""
        raise NotImplementedError

    def _run(self):
        while not self._stop.is_set():
            for cam in self.cameras:
                if self._stop.is_set():
                    break
                frame = self.sources[cam["id"]].grab()
                if frame is None or not self.ready:
                    continue
                try:
                    results = self.infer(cam["id"], frame)
                    if not config.STREAM_ONLY:
                        for data, conf in results:
                            self.emit(cam["id"], self.default_event_type, data, conf)
                    # push frame + kotak deteksi ke server MJPEG (untuk video dashboard)
                    stream_server.publish_annotated(cam["id"], frame, results)
                except Exception as e:
                    log.exception("[%s] infer error @ %s: %s", self.code, cam["id"], e)
            self._stop.wait(config.FRAME_INTERVAL_S)

    default_event_type = "detection"


class PerceptionWorker(BaseWorker):
    """Mendengar metadata objek/track DeepStream dari MQTT."""

    relevant_classes = ()  # filter kelas objek yang diproses

    def __init__(self, mqtt_io):
        super().__init__(mqtt_io)
        self.mqtt.on_perception(self._on_perception)

    def _on_perception(self, topic, payload):
        camera_id = payload.get("cameraId")
        ts = payload.get("ts")
        objects = payload.get("objects", [])
        if self.relevant_classes:
            objects = [o for o in objects if o.get("class") in self.relevant_classes]
        if not objects:
            return
        try:
            self.process(camera_id, ts, objects)
        except Exception as e:
            log.exception("[%s] process error @ %s: %s", self.code, camera_id, e)

    def process(self, camera_id, ts, objects):
        """Override: olah objek, panggil self.emit(...) bila perlu."""
        raise NotImplementedError

    def _run(self):
        # Worker perception bersifat event-driven; loop hanya menjaga thread hidup.
        while not self._stop.is_set():
            self._stop.wait(1.0)
