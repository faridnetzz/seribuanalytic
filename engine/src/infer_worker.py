"""Worker inferensi TUNGGAL (round-robin semua kamera) — kunci throughput tinggi.

Kenapa: menjalankan 5 thread inferensi paralel di 1 GPU + GIL Python = saling rebut
CPU/lock saat CPU jenuh -> tiap inference jadi ~25x lebih lambat dari semestinya
(1.5 fps padahal mampu 30+). GPU malah nganggur (di-starve CPU).

Solusi: SATU thread memutar semua kamera bergiliran. Tiap giliran ambil frame
TERBARU kamera (skip yang basi) lalu jalankan `step(frame)` modul itu. Karena hanya
ada satu thread inferensi, tak ada kontensi antar-inference & gpu.lock tak diperlukan
-> tiap inference full-speed, GPU terpakai efisien, CPU jauh lebih ringan.

Thread grabber (decode) & display (encode) tetap per-kamera — keduanya melepas GIL
saat kerja berat (decode/encode di C), jadi tak menghambat worker.
"""
import logging
import threading
import time

log = logging.getLogger("engine.infer")

_tasks = []
_lock = threading.Lock()
_started = False


def register(cam, grab, step, label, min_interval=0.0, priority=1):
    """Daftarkan satu kamera: grab=LatestFrame, step=fungsi(frame,seq) proses 1 frame.
    min_interval: jeda minimal antar-inferensi kamera ini (detik). 0 = secepat mungkin
    (tracking). Kamera objek statis (sampah) pakai >0 -> sisakan GPU utk kamera tracking.
    priority: jumlah giliran per putaran round-robin (1=normal, 2=2x lebih sering).
    Kamera dgn objek CEPAT (parkir/lalin) pakai >1 -> fps lebih tinggi -> box tak lepas."""
    global _started
    with _lock:
        _tasks.append({"cam": cam, "grab": grab, "step": step, "label": label,
                       "seq": 0, "fps_t": time.time(), "fps_n": 0,
                       "min_interval": float(min_interval), "last_run": 0.0,
                       "priority": max(1, int(priority))})
        if not _started:
            _started = True
            threading.Thread(target=_loop, daemon=True, name="infer-worker").start()
            log.info("Inference worker TUNGGAL aktif (round-robin semua kamera)")


def _loop():
    while True:
        with _lock:
            tasks = list(_tasks)
        if not tasks:
            time.sleep(0.05)
            continue
        # Urutan putaran: semua kamera 1x, lalu giliran EKSTRA utk yg prioritas>1
        # (ditaruh belakang -> terpisah dari giliran pertamanya, biar keburu ada frame baru).
        run = list(tasks) + [t for t in tasks for _ in range(t["priority"] - 1)]
        did = False
        for t in run:
            now0 = time.time()
            if t["min_interval"] and now0 - t["last_run"] < t["min_interval"]:
                continue                              # belum waktunya (objek statis) -> hemat GPU
            frame, seq = t["grab"].get(t["seq"])      # frame TERBARU (skip basi)
            if frame is None:
                continue
            t["seq"] = seq
            t["last_run"] = now0
            did = True
            try:
                t["step"](frame, seq)              # seq utk sinkron box ke frame display
            except Exception as e:
                log.error("[%s] inferensi error: %s", t["label"], e)
            t["fps_n"] += 1
            now = time.time()
            if now - t["fps_t"] >= 15:
                log.info("[%s] %.1f fps inferensi", t["label"], t["fps_n"] / (now - t["fps_t"]))
                t["fps_t"], t["fps_n"] = now, 0
        if not did:
            time.sleep(0.004)                          # semua kamera belum ada frame baru
