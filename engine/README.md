# SIGAP — Engine Inferensi (Python)

"Otak" analitik. Menjalankan model AI 4 modul, bekerja **berdampingan dengan
DeepStream** dalam satu platform. DeepStream menangani decode RTSP + deteksi +
tracking (perception); engine ini menjalankan model spesifik tiap modul lalu
menerbitkan **event final** ke MQTT (`sigap/events/<module>`) yang dikonsumsi backend.

## Pola kerja per modul

| Modul | Pola worker | Sumber input | Model | Status |
|-------|-------------|--------------|-------|--------|
| `parking` | `PerceptionWorker` | track DeepStream (`sigap/perception/#`) | — (logika murni) | **Siap** — zona + dwell |
| `pedestrian` | `PerceptionWorker` | objek 'person' + crop DeepStream | `par_pa100k.onnx`, `reid_osnet.onnx` (ONNX) | Hook PAR + Re-ID |
| `waste` | `FrameWorker` | file `.mp4` / RTSP | `waste.pt` (Ultralytics) | **Tinggal taruh best.pt** |
| `water` | `FrameWorker` | file `.mp4` / RTSP | `water.pt` (Ultralytics) | **Tinggal taruh best.pt** |

> **Degraded otomatis**: jika file model belum ada di `models/`, workernya tetap
> hidup tapi melewati inferensi. Jalankan engine dengan model yang sudah jadi,
> modul lain "menyala" begitu modelnya kamu taruh — tanpa rebuild.

## Menjalankan model `best.pt` (Ultralytics)

1. Latih/ekspor model, simpan sebagai `engine/models/waste.pt` dan/atau `engine/models/water.pt`.
2. (Dev tanpa NVR) taruh video uji `engine/videos/test.mp4` — modul sampah/air
   otomatis membaca file ini (di-loop) alih-alih RTSP. Bisa juga per-kamera: `CAM-03.mp4`.
3. Jalankan: `docker compose --profile gpu up -d --build engine`
4. Pantau: `docker compose logs -f engine` — event muncul di dashboard modul terkait.

**Sampah** ([src/modules/waste.py](src/modules/waste.py)): mendukung model deteksi
maupun segmentasi otomatis. Keparahan dihitung dari proporsi area (`_severity()`).

**Debit air** ([src/modules/water.py](src/modules/water.py)): posisi garis air →
meter via kalibrasi linear per kamera di `config.WATER_CALIBRATION`. Sesuaikan
`_waterline_y()` dengan output kelas modelmu, dan kalibrasi `level_at_y0/y1`.

> Modul `pedestrian` (PAR/Re-ID) tetap memakai ONNX ([src/onnx_util.py](src/onnx_util.py))
> karena bukan tugas YOLO — aktifkan `onnxruntime-gpu` di `requirements.txt` saat
> modelnya siap. Modul `parking` tidak butuh model.

## Konfigurasi (env)

| Var | Default | Keterangan |
|-----|---------|-----------|
| `ENGINE_MODULES` | `pedestrian,waste,water,parking` | modul yang diaktifkan engine ini |
| `MODELS_DIR` | `/opt/engine/models` | lokasi file model |
| `ENGINE_VIDEO_DIR` | `/opt/engine/videos` | folder video uji `.mp4` (dev) |
| `PERCEPTION_TOPIC` | `sigap/perception/#` | topik metadata DeepStream |
| `FRAME_INTERVAL_S` | `5` | jeda sampling frame (modul air/sampah) |
| `MQTT_URL` | `mqtt://mqtt:1883` | broker |

## Kontrak input perception (dari DeepStream)

Topik `sigap/perception/objects`:

```json
{
  "cameraId": "CAM-01",
  "ts": "2026-05-22T14:46:00+07:00",
  "frameId": 12345,
  "objects": [
    {"trackId": 22, "class": "person", "confidence": 0.92,
     "bbox": {"x": 0.31, "y": 0.40, "w": 0.08, "h": 0.30}, "crop": "<base64 jpg|opsional>"},
    {"trackId": 40, "class": "car", "confidence": 0.88,
     "bbox": {"x": 0.55, "y": 0.62, "w": 0.15, "h": 0.18}}
  ]
}
```

bbox **ternormalisasi 0..1**. `crop` opsional (diperlukan untuk PAR/Re-ID).
nvmsgconv DeepStream default tidak menghasilkan format ini — lihat
[../deepstream/README.md](../deepstream/README.md) untuk opsi library msg2p custom
atau adapter penerjemah.

## Jalankan

```bash
# bersama DeepStream (butuh GPU):
docker compose --profile gpu up -d deepstream engine
docker compose logs -f engine
```

Hanya sebagian modul:

```bash
ENGINE_MODULES=parking,water docker compose --profile gpu up -d engine
```
