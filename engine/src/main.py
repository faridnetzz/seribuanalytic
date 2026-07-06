"""Entrypoint engine SIGAP — muat modul aktif, sambung MQTT, jalankan worker."""
import logging
import signal
import time

from . import config
from . import stream_server
from . import hls_proxy
from . import live_stream
from . import pedestrian
from . import parking
from . import roi_store
from . import snapshots
from . import token_refresh
from .mqtt_io import MqttIO
from .modules import build_enabled_workers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("engine")


def main():
    log.info("SIGAP engine start — modul aktif: %s", config.ENABLED_MODULES)
    mqtt_io = MqttIO()
    workers = build_enabled_workers(mqtt_io)
    # Sambung MQTT setelah worker terdaftar (subscriber perception sudah siap).
    mqtt_io.connect()

    stream_server.start(config.STREAM_PORT)   # server MJPEG frame teranotasi
    if config.LIVE_ENABLED:                   # streaming live mulus + emit event asli
        roi_store.load()                      # ROI parkir tersimpan (digambar via dashboard)
        snapshots.load()                      # galeri snapshot wajah/tubuh tersimpan
        hls_proxy.start(config.HLS_PROXY_PORT)
        token_refresh.start()                 # ambil token terbaru sebelum reader mulai
        live_stream.start(mqtt_io)            # sampah (CAM-02)
        pedestrian.start(mqtt_io)             # pedestrian + FR (CAM-05, CAM-07)
        parking.start(mqtt_io)                # parkir liar ROI+dwell (CAM-01, CAM-04)

    for w in workers:
        w.start()

    running = {"on": True}

    def shutdown(*_):
        log.info("Mematikan engine...")
        running["on"] = False
        for w in workers:
            w.stop()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while running["on"]:
        time.sleep(1)
    log.info("Engine berhenti.")


if __name__ == "__main__":
    main()
