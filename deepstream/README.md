# SIGAP — DeepStream (Perception Backbone)

DeepStream berperan sebagai **tulang punggung perception**: decode RTSP 8 kamera,
deteksi objek (orang+kendaraan), dan tracking ID persisten — semua di GPU.
Outputnya (metadata objek+track) diterbitkan ke MQTT `sigap/perception/*` dan
**dikonsumsi oleh engine Python** ([../engine](../engine)) yang menjalankan model
spesifik tiap modul. Pembagian ini = "DeepStream lihat & lacak, engine berpikir".

**Status: template** — isi model & RTSP nyata sebelum produksi. Saat dev tanpa
GPU, gunakan service `simulator` yang langsung menerbitkan event final.

## Arsitektur (DeepStream + Engine)

```
RTSP CCTV (8 titik)
   │
   ▼  nvstreammux (batch=8)
PGIE  : detector orang + kendaraan        (config_pgie_detector.txt)
   │
   ▼  NvDCF tracker (ID persisten)         (config_tracker.yml)
   ▼  nvmsgconv  (payload perception)      (config_msgconv.txt)
   ▼  nvmsgbroker (MQTT)                   (cfg_mqtt.txt)
        │  topic: sigap/perception/objects
        ▼
   Engine Python  ── model per modul ──▶  MQTT sigap/events/<module>
        │                                         │
        │  (PAR/ReID, sampah, air, parkir)        ▼
        └───────────────────────────────▶  backend → PostgreSQL → dashboard
```

## Pembagian peran modul

| Modul | DeepStream | Engine Python |
|-------|-----------|---------------|
| **Pedestrian** | deteksi person + track (+ crop) | PAR 11 atribut + Re-ID lintas kamera |
| **Parkir liar** | deteksi vehicle + track | logika zona poligon + dwell time |
| **Sampah** | (opsional) — | segmentasi frame penuh |
| **Debit air** | (opsional) — | estimasi ketinggian (staff gauge) |

> SGIE PAR di pipeline DeepStream **dinonaktifkan default** (`enable=0`) karena
> PAR/Re-ID dijalankan engine. Aktifkan kembali hanya bila ingin PAR di dalam
> DeepStream. Modul sampah & air berbasis frame penuh sehingga ditangani engine
> (boleh juga jadi pipeline DeepStream terpisah bila modelmu cocok).

## Mengirim crop objek ke engine (untuk PAR/Re-ID)

PAR & Re-ID butuh potongan citra ('crop') tiap orang. Agar `objects[].crop`
terisi base64 JPEG, aktifkan encoding crop objek (mis. via
`nvds_obj_enc` / library msg2p custom). Tanpa crop, worker pedestrian jalan
degraded (lihat [../engine/README.md](../engine/README.md)).

## Kontrak payload perception (DeepStream → engine)

Topik `sigap/perception/objects` — metadata objek+track per frame:

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

`nvmsgconv` default DeepStream menghasilkan skema NVIDIA, **bukan** format ini.
Dua opsi untuk menjembatani:
1. **Library msg2p custom** (`msg-conv-payload-type` ≥ 256) yang menulis format di atas — disarankan.
2. **Adapter ringan**: publish skema default DeepStream apa adanya, lalu service
   kecil menerjemahkannya ke format perception ini. Engine yang menanti format ini.

> Backend **tidak** mendengar `sigap/perception/*` — hanya `sigap/events/*`.
> Event final yang masuk DB selalu dihasilkan engine (atau simulator).

## Menjalankan (butuh GPU + NVIDIA Container Toolkit)

```bash
# Taruh model di deepstream/models/ (lihat .gitkeep)
docker compose stop simulator                       # matikan event dummy
docker compose --profile gpu up -d deepstream engine # backbone + otak
docker compose logs -f deepstream engine
```

## Membuat TensorRT engine

Engine `.engine` dibuat otomatis saat run pertama dari `onnx-file`, atau manual:

```bash
trtexec --onnx=models/detector.onnx --saveEngine=models/detector.engine --fp16
```
