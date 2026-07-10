"""Konfigurasi engine — dibaca dari environment dengan default aman."""
import os
import socket

MQTT_URL = os.getenv("MQTT_URL", "mqtt://localhost:1883")
# ID klien MQTT HARUS UNIK per container. Dua container (engine + engine-ped) memakai
# image yang sama; bila client_id kembar, broker menendang yang lama ("session taken
# over") -> loop reconnect tak henti + event bisa hilang. Fallback ke hostname (unik).
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID") or f"sigap-engine-{socket.gethostname()}"


def _camlist(env, default):
    """Daftar kamera dari env (comma-separated). MULTIPROCESS: tiap container engine
    menangani subset kamera (env kosong "" = pipeline itu mati di container ini)."""
    v = os.getenv(env)
    if v is None:
        return list(default)
    return [c.strip() for c in v.split(",") if c.strip()]

# Modul yang diaktifkan engine ini (sisanya bisa ditangani DeepStream murni).
# Contoh: ENGINE_MODULES=water,waste
ENABLED_MODULES = [
    m.strip()
    for m in os.getenv("ENGINE_MODULES", "pedestrian,waste,water,parking").split(",")
    if m.strip()
]

# Direktori model (.pt). Di-mount sebagai volume di docker-compose.
MODELS_DIR = os.getenv("MODELS_DIR", "/opt/engine/models")

# Direktori video uji (.mp4) untuk dev sebelum ada akses RTSP/NVR.
# Jika ada file <CAM-ID>.mp4 atau test.mp4 di sini, modul berbasis frame
# (sampah/air) memakainya sebagai ganti RTSP — di-loop terus.
VIDEO_DIR = os.getenv("ENGINE_VIDEO_DIR", "/opt/engine/videos")

# Topik perception dari DeepStream (objek terdeteksi + track).
PERCEPTION_TOPIC = os.getenv("PERCEPTION_TOPIC", "sigap/perception/#")

# Topik publish event final (per modul ditambahkan di belakang).
EVENT_TOPIC_PREFIX = os.getenv("EVENT_TOPIC_PREFIX", "sigap/events")

# FPS sampling untuk modul berbasis frame (air/sampah tidak perlu real-time).
FRAME_INTERVAL_S = float(os.getenv("FRAME_INTERVAL_S", "5"))

# Port server MJPEG (frame teranotasi) untuk video live di dashboard.
STREAM_PORT = int(os.getenv("STREAM_PORT", "8090"))

# Mode stream-only: tetap deteksi & sajikan video, TAPI tidak publish event MQTT
# (dipakai saat data event dashboard sengaja diisi simulator/dummy).
STREAM_ONLY = os.getenv("STREAM_ONLY", "false").lower() in ("1", "true", "yes")

# --- Streaming LIVE (mulus, pola test.py) ---
# Bila aktif, kamera di LIVE_STREAMS pakai stream HLS live seribuwajah (via proxy
# internal) + buffer thread, BUKAN video rekaman. FrameWorker melewati kamera ini.
LIVE_ENABLED = os.getenv("LIVE_ENABLED", "false").lower() in ("1", "true", "yes")
LIVE_HLS_KEY_URL = os.getenv(
    "LIVE_HLS_KEY_URL",
    "https://sliceseribuwajah.bandarlampungkota.go.id/encryption.key")
HLS_PROXY_PORT = int(os.getenv("HLS_PROXY_PORT", "8787"))

_BASE = "https://sliceseribuwajah.bandarlampungkota.go.id/resource/stream?key="
# Semua kamera live: cam_id -> manifest URL seribuwajah (key endpoint sama untuk semua).
LIVE_CAMERAS = {
    "CAM-02": os.getenv("CAM02_MANIFEST", _BASE + "1775807311736"),  # sampah (Lorong Pasar SMEP)
    "CAM-03": os.getenv("CAM03_MANIFEST", _BASE + "1775809069703"),  # sampah (Pasar Gintung)
    # CAM-05 (Jembatan Milenial 1) PINDAH ke skema EMBED baru -> lihat LIVE_EMBED_CAMERAS.
    "CAM-06": os.getenv("CAM06_MANIFEST", _BASE + "1775806766083"),  # pedestrian (Jembatan Milenial 3) — BERDEKATAN dgn CAM-05 (jejak lintas-kamera)
    "CAM-07": os.getenv("CAM07_MANIFEST", _BASE + "1775808621943"),  # pedestrian (Kelurahan Gulak Galik)
    "CAM-01": os.getenv("CAM01_MANIFEST", _BASE + "1775810152498"),  # parkir (Yos Sudarso - M. Salim)
    "CAM-04": os.getenv("CAM04_MANIFEST", _BASE + "1774458088756"),  # parkir (ZA Pagar Alam Depan DKP)
} if LIVE_ENABLED else {}


# Kamera skema EMBED baru (newseribuwajah). Auth berbasis COOKIE (bukan AES):
# GET api embed -> set cookie stream_token (3 jam) + streamUrl(master m3u8) ->
# GET master (redirect cookieCheck -> set hlsSession) -> variant media playlist
# (segmen .ts POLOS, tanpa enkripsi). hls_proxy menangani sesi cookie + resolve variant.
LIVE_EMBED_CAMERAS = {
    "CAM-05": {
        "api": os.getenv(
            "CAM05_EMBED_API",
            "https://newseribuwajah.bandarlampungkota.go.id/api/cctvs/public/embed/22"),
        "referer": os.getenv("CAM05_EMBED_REFERER", "https://newseribuwajah.bandarlampungkota.go.id/"),
    },
} if LIVE_ENABLED else {}
# Re-auth sesi embed (token stream_token berlaku 3 jam) — perbarui sebelum kadaluarsa.
EMBED_SESSION_TTL = float(os.getenv("EMBED_SESSION_TTL", "9000"))   # 2.5 jam


def live_playlist_url(cam):
    return f"http://127.0.0.1:{HLS_PROXY_PORT}/playlist/{cam}"


# Auto-refresh token: CAM-ID -> NAMA kamera persis di /cctv-public/ (token berubah
# berkala; nama tetap). CAM-02 (sampah) belum ditemukan namanya -> belum di-refresh.
CAM_NAMES = {
    # CAM-02 (Lorong Pasar SMEP) TIDAK di sini: tak ada di /cctv-public/ -> token
    # statis (manual). Bila stream mati lagi, ganti CAM02_MANIFEST/default token.
    # CAM-05 TIDAK di sini: pakai skema EMBED (LIVE_EMBED_CAMERAS), bukan token ?key= -> jangan ditimpa token-refresh.
    "CAM-06": os.getenv("CAM06_NAME", "Jembatan Millenial 3"),   # nama /cctv-public (sesuaikan bila auto-refresh tak match)
    "CAM-07": os.getenv("CAM07_NAME", "Kelurahan Gulak Galik"),
    "CAM-01": os.getenv("CAM01_NAME", "Pertigaan Yos Sudarso - Mochammad Salim"),
    "CAM-04": os.getenv("CAM04_NAME", "Tugu Selamat Jln Bandar Lampung"),
}
TOKEN_REFRESH_INTERVAL = float(os.getenv("TOKEN_REFRESH_INTERVAL", "300"))  # 5 menit
TOKEN_REFRESH_MIN_GAP = float(os.getenv("TOKEN_REFRESH_MIN_GAP", "25"))     # throttle


# Kamera sampah (live) — FrameWorker melewati kamera ini (ditangani live_stream).
LIVE_STREAMS = {c: live_playlist_url(c) for c in _camlist("WASTE_CAMERAS", ("CAM-02", "CAM-03"))} if LIVE_ENABLED else {}
# Kamera pedestrian (live) — ditangani pipeline pedestrian + FR. CAM-05 & CAM-06
# (Jembatan Milenial 1 & 3) BERDEKATAN -> jejak lintas-kamera bermakna.
PED_CAMERAS = _camlist("PED_CAMERAS", ("CAM-05", "CAM-06", "CAM-07")) if LIVE_ENABLED else []
# skip_frozen MATIKAN utk pedestrian: tracking tak mengukur dwell, jadi tak butuh
# buang frame beku. Membuang frame beku JUSTRU bikin buffer playout kelaparan saat
# adegan diam -> video patah/freeze. Mati = semua frame masuk buffer -> MULUS (spt waste).
PED_SKIP_FROZEN = os.getenv("PED_SKIP_FROZEN", "false").lower() in ("1", "true", "yes")
# Kamera parkir liar (live) — ditangani pipeline parking (ROI + dwell time).
PARK_CAMERAS = _camlist("PARK_CAMERAS", ("CAM-01", "CAM-04")) if LIVE_ENABLED else []
# skip_frozen utk parkir: default NYALA (cegah dwell palsu saat freeze). Catatan:
# proteksi freeze parkir juga sudah ditangani PARK_FREEZE_GAP_S di step(), jadi ini
# bisa dimatikan demi kemulusan tanpa kehilangan proteksi (uji dulu).
PARK_SKIP_FROZEN = os.getenv("PARK_SKIP_FROZEN", "true").lower() in ("1", "true", "yes")
PARK_CONF = float(os.getenv("PARK_CONF", "0.35"))
PARK_CLASSES = [2, 3, 5, 7]                           # car, motorcycle, bus, truck (COCO)
# imgsz inferensi khusus parkir: lebih kecil dari global (320) -> inferensi lebih cepat
# -> fps parkir naik -> box menempel lebih rapat ke kendaraan (kurangi "lepas"). Kendaraan
# objek besar shg tetap terdeteksi baik di 288. Turunkan lagi (256) bila mau lebih cepat.
PARK_INFER_IMGSZ = int(os.getenv("PARK_INFER_IMGSZ", "288"))
PARK_INFER_PRIORITY = int(os.getenv("PARK_INFER_PRIORITY", "2"))  # giliran inferensi ekstra/putaran (2 = 2x lebih sering)
PARK_DWELL_S = float(os.getenv("PARK_DWELL_S", "20"))    # ambang parkir liar default (detik); diubah per-kamera dari dashboard
# Grace BESAR: slot parkir dianggap MASIH terisi sampai tak ada kendaraan di lokasinya
# > grace detik. Menyerap kedipan deteksi / fps rendah / stream putus -> parkir TAK
# reset walau bounding box lepas sesaat. Mobil benar2 pergi baru di-finalisasi.
PARK_GRACE_S = float(os.getenv("PARK_GRACE_S", "40"))   # besar: kendaraan parkir tetap 1 sesi walau deteksi hilang lama (stall/segmen rusak)
# Cocokkan deteksi ke slot parkir (occupancy by LOKASI, bukan track id):
# - jarak PUSAT < PARK_MATCH_DIST * dimensi box (tahan jitter UKURAN bbox), ATAU IoU.
PARK_MATCH_IOU = float(os.getenv("PARK_MATCH_IOU", "0.30"))
PARK_MATCH_DIST = float(os.getenv("PARK_MATCH_DIST", "0.6"))
PARK_BOX_EMA = float(os.getenv("PARK_BOX_EMA", "0.4"))  # smoothing bbox slot -> box stabil, tak lepas/jitter
# Gerbang gerak: kalau pusat kendaraan menjauh > PARK_MOVE_FRAC * dimensi-box dari
# anchor -> dianggap BERGERAK (lewat) -> dwell di-reset. Cegah kendaraan jalan keflag
# parkir (incl. saat frame freeze 'mengikuti' kendaraan). Parkir nyata diam < ambang ini.
PARK_MOVE_FRAC = float(os.getenv("PARK_MOVE_FRAC", "0.5"))
# Ambang JEDA observasi (detik). Bila selang antar-frame yang DIPROSES melebihi ini,
# berarti ada freeze/stall/reconnect (frame beku dibuang grabber atau stream putus) —
# jam dinding jalan tapi kendaraan TAK teramati. Interval ini TIDAK dihitung sbg dwell
# (cegah PARKIR LIAR palsu saat stream freeze). Set di atas selang inferensi normal.
PARK_FREEZE_GAP_S = float(os.getenv("PARK_FREEZE_GAP_S", "2.5"))
# KONTINUITAS IDENTITAS slot (anti akumulasi LINTAS-KENDARAAN). Slot dicocokkan by
# LOKASI; di jalan ramai, kendaraan A pergi lalu B (lain) berhenti/lewat di titik sama
# dalam masa grace -> timer dwell A diwarisi B -> PARKIR LIAR palsu. Penjaga: bila ID
# track penghuni slot BERGANTI ke ID yg tak terlihat di slot ini dlm PARK_ID_MEMORY_S
# detik DAN posisinya bergeser > PARK_ID_MOVE_FRAC*dimensi dari anchor -> KENDARAAN LAIN
# -> mulai sesi baru. ID berganti TAPI posisi persis sama = ID-switch mobil yg sama
# (parkir diam) -> JANGAN reset. Mobil parkir diam -> ID BoT-SORT stabil -> timer jalan.
PARK_ID_MEMORY_S = float(os.getenv("PARK_ID_MEMORY_S", "6"))
PARK_ID_MOVE_FRAC = float(os.getenv("PARK_ID_MOVE_FRAC", "0.2"))
PARK_SNAP_MAX = int(os.getenv("PARK_SNAP_MAX", "200"))   # batas snapshot pelanggaran parkir
ROI_FILE = os.getenv("ROI_FILE", "/opt/engine/data/roi.json")  # ROI digambar via dashboard
# Jeda nyalakan kamera satu-per-satu (detik) — cegah GIL/upstream starvation saat
# startup serempak (tiap kamera "established" dulu sebelum yang berikut).
CAM_STAGGER_S = float(os.getenv("CAM_STAGGER_S", "3"))
# Ukuran inference YOLO. 480 (bukan 640) ~2x lebih cepat di GPU -> lock cepat
# dilepas -> 5 kamera kebagian merata & lancar. Cukup utk deteksi orang/kendaraan.
INFER_IMGSZ = int(os.getenv("INFER_IMGSZ", "320"))   # 320 (bukan 480) ~2.25x lebih cepat -> fps inferensi naik -> box ngetrack rapat
# FP16 (half precision) di GPU: ~2x lebih cepat & hemat VRAM -> lock cepat lepas,
# kamera kebagian GPU lebih merata. Tensor core CUDA dipakai penuh.
INFER_HALF = os.getenv("INFER_HALF", "true").lower() == "true"
# Konfigurasi tracker (BoT-SORT persisten) — kurangi ID switch / snapshot dobel.
TRACKER_CFG = os.getenv("TRACKER_CFG", "/opt/engine/src/tracker.yaml")
LIVE_FPS = float(os.getenv("LIVE_FPS", "20"))
# Buffer playout SWEET-SPOT (~0.75s): cukup meredam jitter HLS publik (video tak
# patah-patah) tapi delay kecil/terasa realtime. Akurasi box & parkir TIDAK bergantung
# buffer (occupancy spasial + box-sync), jadi aman dinaikkan demi kemulusan.
LIVE_BUFFER = int(os.getenv("LIVE_BUFFER", "30"))
LIVE_PREBUFFER = int(os.getenv("LIVE_PREBUFFER", "15"))
# Output MJPEG: downscale + quality -> encode JPEG jauh lebih ringan (CPU/GIL) &
# bandwidth kecil. Card dashboard tak butuh 1080p penuh. 0 = tanpa downscale.
# 640px cukup utk card dashboard; encode kecil -> display tak menyetarvasi inferensi.
STREAM_MAX_W = int(os.getenv("STREAM_MAX_W", "640"))
STREAM_JPEG_Q = int(os.getenv("STREAM_JPEG_Q", "62"))
LIVE_CONF = float(os.getenv("LIVE_CONF", "0.30"))    # ambang deteksi sampah (0.30: lebih sensitif dari 0.40 tapi tak banjir kotak skor-rendah)
# Sampah sering kecil/jauh -> inferensi pakai resolusi LEBIH BESAR (640, bukan 320)
# biar tumpukan kecil ke-deteksi. Kamera sampah infer jarang (tiap 2s) jadi murah.
WASTE_IMGSZ = int(os.getenv("WASTE_IMGSZ", "640"))
# Buang kotak RAKSASA skor-rendah (deteksi palsu menutup hampir seluruh frame) &
# noise mungil. Tumpukan sampah nyata proporsional, tak menutup >40% frame.
WASTE_MAX_AREA = float(os.getenv("WASTE_MAX_AREA", "0.40"))   # rasio area thd frame
WASTE_MIN_AREA = float(os.getenv("WASTE_MIN_AREA", "0.0008"))
# Occupancy TUMPUKAN (episode persistensi): cocokkan deteksi ke tumpukan by IoU;
# tumpukan tak terlihat > grace dianggap diangkut. Heartbeat update durasi.
WASTE_MATCH_IOU = float(os.getenv("WASTE_MATCH_IOU", "0.30"))
WASTE_GRACE_S = float(os.getenv("WASTE_GRACE_S", "25"))       # hilang > ini = diangkut/hilang
WASTE_HEARTBEAT_S = float(os.getenv("WASTE_HEARTBEAT_S", "15"))  # update durasi ke backend tiap N detik
# Jeda emit event deteksi dari kamera live (detik). Video tetap 25fps; event
# tidak perlu 25/detik agar DB tidak banjir.
LIVE_EVENT_INTERVAL = float(os.getenv("LIVE_EVENT_INTERVAL", "5"))

# --- Face Recognition (insightface antelopev2) ---
FACE_MODEL_ROOT = os.getenv("FACE_MODEL_ROOT", os.path.join(MODELS_DIR, "insightface"))
FACE_MODEL_NAME = os.getenv("FACE_MODEL_NAME", "antelopev2")
FACE_DET_SIZE = int(os.getenv("FACE_DET_SIZE", "384"))   # 384 (bukan 640): face-det insightface jauh lebih ringan -> worker tunggal lebih cepat -> fps tracking semua kamera naik
FACE_MATCH_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", "0.35"))  # cosine glintr100
# Folder enrollment wajah: ENROLL_DIR/<Nama>/*.jpg
ENROLL_DIR = os.getenv("ENROLL_DIR", "/opt/engine/enrollment")
# Model deteksi orang (pedestrian)
PERSON_MODEL = os.getenv("PERSON_MODEL", os.path.join(MODELS_DIR, "person.pt"))
PED_CONF = float(os.getenv("PED_CONF", "0.40"))      # ambang deteksi orang
FR_EVERY = int(os.getenv("FR_EVERY", "20"))          # jalankan FR tiap N frame (hemat GPU -> fps tracking naik)
TRAIL_LEN = int(os.getenv("TRAIL_LEN", "32"))        # panjang jejak lintasan (trajectory) per orang di video
# --- Pedestrian Attribute Recognition (PAR, port oss_vision) ---
# Atribut: gender/usia (dari FR), warna atasan/bawahan (HSV), aksesori (topi/tas/
# masker). Diakumulasi per-track lintas frame -> stabil. CPU-only (selain FR).
# PAR warna baju/aksesori DIMATIKAN (heuristik HSV banyak salah & bikin overlay
# berantue). Overlay video -> #ID/nama saja; distribusi atribut kosong. Gender/usia
# tetap dari FR utk galeri. Nyalakan lagi: ATTR_ENABLED=true.
ATTR_ENABLED = os.getenv("ATTR_ENABLED", "false").lower() in ("1", "true", "yes")
ATTR_EVERY = int(os.getenv("ATTR_EVERY", "8"))       # ekstrak warna/aksesori tiap N frame per-track
# Galeri snapshot: auto-capture tiap orang (tubuh+wajah) + metadata; klik utk enroll.
SNAP_DIR = os.getenv("SNAP_DIR", "/opt/engine/data/snapshots")
SNAP_MAX = int(os.getenv("SNAP_MAX", "500"))         # batas snapshot tersimpan (FIFO)
SNAP_MIN_H = int(os.getenv("SNAP_MIN_H", "170"))     # tinggi bbox minimal (px) — hanya orang DEKAT (lebih tajam)
# Padding crop tubuh: box YOLO sering memotong kepala (bahu ke atas) di sudut CCTV.
# Perlebar box saat crop+gambar supaya KEPALA ikut terambil dari frame (fraksi dari dimensi box).
SNAP_PAD_TOP = float(os.getenv("SNAP_PAD_TOP", "0.35"))   # atas: pulihkan kepala yg dipotong box
SNAP_PAD_X = float(os.getenv("SNAP_PAD_X", "0.10"))       # kiri/kanan
SNAP_PAD_BOT = float(os.getenv("SNAP_PAD_BOT", "0.05"))   # bawah
SNAP_TRIES = int(os.getenv("SNAP_TRIES", "16"))      # evaluasi N frame pertama, pilih TERTAJAM
SNAP_SHARP_OK = float(os.getenv("SNAP_SHARP_OK", "500"))  # ketajaman cukup -> commit cepat
SNAP_MIN_SHARP = float(os.getenv("SNAP_MIN_SHARP", "60"))  # buang frame super-buram (jangan disimpan sama sekali)
SNAP_DEDUP_THRESH = float(os.getenv("SNAP_DEDUP_THRESH", "0.45"))  # cosine sim wajah >= ini = orang sama -> skip dobel
SNAP_DEDUP_WINDOW = float(os.getenv("SNAP_DEDUP_WINDOW", "300"))   # rentang waktu (detik) cek duplikat wajah (5 mnt)
# Dedup TUBUH (histogram warna) — dipakai saat wajah tak terlihat (mayoritas CCTV).
# Cegah orang sama ke-snapshot berkali saat track ID pecah. Threshold lebih tinggi +
# window lebih pendek dari wajah krn warna kurang unik (hindari beda orang ke-merge).
SNAP_BODY_THRESH = float(os.getenv("SNAP_BODY_THRESH", "0.62"))    # cosine histogram tubuh >= ini = orang sama
SNAP_BODY_WINDOW = float(os.getenv("SNAP_BODY_WINDOW", "180"))     # rentang waktu (detik) cek duplikat tubuh (3 mnt)
# Trajektori lintas-kamera: sighting kamera SAMA dlm < gap detik digabung jadi 1
# kunjungan (biar jejak ringkas: 1 baris per kunjungan-kamera, bukan per-deteksi).
SIGHT_GAP_S = float(os.getenv("SIGHT_GAP_S", "30"))

# Pemetaan kamera -> RTSP. Tahap awal hardcode (selaras db seed); idealnya
# diambil dari API backend /api/cameras saat startup.
CAMERAS = {
    "CAM-01": {"rtsp": "rtsp://edge/cam01", "modules": ["parking", "pedestrian"]},
    "CAM-02": {"rtsp": "rtsp://edge/cam02", "modules": ["waste", "pedestrian"]},
    "CAM-03": {"rtsp": "rtsp://edge/cam03", "modules": ["water", "waste"]},
    "CAM-04": {"rtsp": "rtsp://edge/cam04", "modules": ["parking"]},
    "CAM-05": {"rtsp": "rtsp://edge/cam05", "modules": ["pedestrian", "parking"]},
    "CAM-06": {"rtsp": "rtsp://edge/cam06", "modules": ["water"]},
    "CAM-07": {"rtsp": "rtsp://edge/cam07", "modules": ["pedestrian"]},
    "CAM-08": {"rtsp": "rtsp://edge/cam08", "modules": ["pedestrian", "waste"]},
}

# Zona parkir terlarang per kamera (poligon ternormalisasi 0..1) + ambang dwell.
PARKING_ZONES = {
    "CAM-01": [{"name": "Dilarang Parkir — Badan Jalan",
                "polygon": [[0.10, 0.55], [0.85, 0.55], [0.85, 0.95], [0.10, 0.95]],
                "dwell_limit_s": 180}],
    "CAM-04": [{"name": "Marka Kuning",
                "polygon": [[0.05, 0.60], [0.60, 0.60], [0.60, 0.92], [0.05, 0.92]],
                "dwell_limit_s": 300}],
    "CAM-05": [{"name": "Zona Pejalan Kaki",
                "polygon": [[0.30, 0.50], [0.95, 0.50], [0.95, 0.90], [0.30, 0.90]],
                "dwell_limit_s": 240}],
}


# Kalibrasi virtual staff gauge: posisi garis air (y ternormalisasi 0=atas
# frame, 1=bawah) -> ketinggian meter, interpolasi linear per kamera.
# SESUAIKAN dengan geometri kamera sungai Anda.
WATER_CALIBRATION = {
    "CAM-03": {"level_at_y0": 3.0, "level_at_y1": 0.0},
    "CAM-06": {"level_at_y0": 4.0, "level_at_y1": 0.0},
}
WATER_CALIBRATION_DEFAULT = {"level_at_y0": 3.0, "level_at_y1": 0.0}


def cameras_for(module: str):
    """Daftar kamera (id, rtsp) yang menjalankan modul tertentu."""
    return [
        {"id": cid, "rtsp": c["rtsp"]}
        for cid, c in CAMERAS.items()
        if module in c["modules"]
    ]


def source_for(camera_id: str) -> dict:
    """Tentukan sumber frame kamera: file video uji bila ada, jika tidak RTSP.

    Mengembalikan {"type": "file"|"rtsp", "path": ...}.
    """
    rtsp = CAMERAS.get(camera_id, {}).get("rtsp", "")
    for candidate in (f"{camera_id}.mp4", "test.mp4"):
        path = os.path.join(VIDEO_DIR, candidate)
        if os.path.exists(path):
            return {"type": "file", "path": path}
    return {"type": "rtsp", "path": rtsp}


def water_calibration(camera_id: str) -> dict:
    return WATER_CALIBRATION.get(camera_id, WATER_CALIBRATION_DEFAULT)
