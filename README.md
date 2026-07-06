# SIGAP — Analitik CCTV Kota Bandar Lampung

**Sistem Intelijen Gabungan Analitik Pengawasan.** Platform analitik video real-time
untuk 4 modul kecerdasan buatan, mengolah arus CCTV kota (sumber:
[Seribu Wajah Bandar Lampung](https://seribuwajah.bandarlampungkota.go.id)).

| Modul | Fungsi | Teknik |
|-------|--------|--------|
| 🚶 **Pedestrian** | Atribut orang (gender, usia, helm, tas…) + pelacakan lintas-kamera | PAR + ReID |
| 🗑️ **Sampah** | Titik tumpukan sampah liar & sampah mengambang | Segmentasi |
| 💧 **Debit Air** | Ketinggian muka air sungai + status banjir | Virtual Staff Gauge |
| 🚗 **Parkir Liar** | Kendaraan di zona terlarang | Zona + Dwell Time |

## Arsitektur

Pipeline produksi memakai pola **hybrid**: DeepStream sebagai *perception
backbone* (decode + deteksi + tracking di GPU), dan **engine Python** sebagai
*otak* yang menjalankan model tiap modul. Keduanya jalan berdampingan dalam satu
platform dan terhubung lewat MQTT.

```
                ┌──────────────┐   sigap/perception/*   ┌──────────────┐
   CCTV RTSP ──▶│  DeepStream  │──────────────────────▶ │ Engine Python│
                │ detect+track │                         │ model/modul  │
                └──────────────┘                         └──────┬───────┘
   [dev] Simulator ───────────────────────────┐                │ sigap/events/*
                                               ▼                ▼
                                        ┌─────────────┐   ┌──────────────┐
                                        │  Mosquitto  │──▶│   Backend    │ consumer+REST+WS
                                        │   (MQTT)    │   │  (Node.js)   │
                                        └─────────────┘   └──────┬───────┘
                                                                 │       ┌────────────┐
                                                                 ├─────▶ │ PostgreSQL │
                                                                 ▼ REST+WS└────────────┘
                                                          ┌──────────────┐
                                                          │  Dashboard   │ Vue 3 (nginx)
                                                          └──────────────┘
```

Backend hanya mendengar `sigap/events/*` (event final). Output mentah DeepStream
mengalir di `sigap/perception/*` dan dikonsumsi engine — tidak langsung ke DB.

| Service | Teknologi | Port | Peran |
|---------|-----------|------|------|
| `postgres` | PostgreSQL 16 | 5432 | Penyimpanan event, track, alert |
| `mqtt` | Mosquitto 2 | 1883 / 9001 | Message bus (perception + events) |
| `backend` | Node.js 20 (Express + ws + pg + mqtt) | 4000 | Consumer event, REST API, WebSocket |
| `simulator` | Node.js 20 | – | Event dummy 4 modul (dev tanpa GPU) |
| `dashboard` | Vue 3 + Vite + Pinia (nginx) | 8080 | Antarmuka operator |
| `deepstream` | NVIDIA DeepStream 7.0 | – | Perception: decode+detect+track (profil `gpu`) |
| `engine` | Python 3 + ONNX Runtime (CUDA) | – | Otak: model 4 modul (profil `gpu`) |

## Mulai cepat (tanpa GPU)

```bash
cp .env.example .env
docker compose up -d --build      # postgres, mqtt, backend, simulator, dashboard
```

- Dashboard  → http://localhost:8080
- REST API   → http://localhost:4000/api  (cek: `/api/health`)
- WebSocket  → ws://localhost:4000/ws

Simulator mulai menghasilkan event 4 modul; KPI, grafik, dan aliran alert di
dashboard terisi otomatis dalam beberapa detik.

### Mengaktifkan pipeline nyata: DeepStream + Engine (GPU)

Butuh GPU NVIDIA + [NVIDIA Container Toolkit], model DeepStream di
`deepstream/models/`, dan model engine di `engine/models/`.

```bash
docker compose stop simulator                        # matikan event dummy
docker compose --profile gpu up -d deepstream engine # backbone + otak
docker compose logs -f deepstream engine
```

- **DeepStream** decode RTSP + deteksi + tracking → `sigap/perception/*`
- **Engine** menjalankan model 4 modul → `sigap/events/*` → backend → dashboard

Modul yang modelnya belum siap akan jalan *degraded* (tidak inferensi) dan
"menyala" begitu file modelnya ditaruh — tak perlu rebuild. Pilih modul aktif
via `ENGINE_MODULES` (mis. `ENGINE_MODULES=parking,water`).

Detail: [deepstream/README.md](deepstream/README.md) · [engine/README.md](engine/README.md).

## Pengembangan lokal (tanpa Docker untuk app)

```bash
# Infra dasar saja
docker compose up -d postgres mqtt

# Backend
cd backend && npm install && npm run dev

# Simulator (opsional)
cd simulator && npm install && npm start

# Dashboard (Vite dev server + proxy ke :4000)
cd dashboard && npm install && npm run dev   # http://localhost:5173
```

## Struktur proyek

```
.
├── docker-compose.yml      # orkestrasi semua service
├── .env.example
├── db/init/                # skema + seed PostgreSQL (auto-run)
├── mqtt/                   # konfigurasi Mosquitto
├── backend/                # Node.js: REST + WS + consumer MQTT
│   └── src/{routes,mqtt,ws}
├── simulator/              # generator event dummy → MQTT
├── deepstream/             # perception backbone (configs + Dockerfile)
├── engine/                 # otak inferensi Python (model 4 modul)
│   └── src/{modules,mqtt_io,frame_source}
└── dashboard/              # Vue 3 SPA (Vite)
    └── src/{views,components,stores,api}
```

## Kontrak pesan MQTT

Dua jalur topik yang dipisah:

- `sigap/perception/*` — output mentah DeepStream (objek+track per frame) → **engine**
- `sigap/events/<module>` — event final dari engine/simulator → **backend → DB**

### Event final (`sigap/events/<module>`)

```json
{
  "messageId": "uuid",
  "ts": "2026-05-22T14:46:00+07:00",
  "cameraId": "CAM-01",
  "module": "parking",
  "eventType": "violation",
  "confidence": 0.93,
  "data": { "zoneName": "Marka Kuning", "vehicleType": "mobil", "dwellSeconds": 420 }
}
```

Backend menulis ke `detection_events` + tabel modul, menerapkan aturan alert
(mis. dwell > 5/10 mnt, kenaikan air > 10 cm/30 mnt, sampah severity tinggi),
lalu menyiarkan event & alert ke dashboard via WebSocket.

## Endpoint API utama

| Method | Path | Keterangan |
|--------|------|-----------|
| GET | `/api/health` | Status service + DB |
| GET | `/api/overview` | KPI, kartu modul, volume/jam, kontribusi |
| GET | `/api/cameras` | Daftar kamera + deteksi hari ini |
| GET | `/api/alerts?limit=` | Aliran alert terbaru |
| POST | `/api/alerts/:id/ack` | Tandai alert ditindak |
| GET | `/api/pedestrian/summary` · `/tracks` | Ringkasan & track pedestrian |
| GET | `/api/waste/summary` · `/recent` | Ringkasan & deteksi sampah |
| GET | `/api/water/summary` · `/series?camera=` | Stasiun & tren air |
| GET | `/api/parking/summary` · `/violations` | Ringkasan & pelanggaran parkir |

## Catatan

- **Keamanan**: tahap awal memakai MQTT anonim & password DB default. Sebelum
  produksi, aktifkan auth Mosquitto/TLS, ganti kredensial, dan batasi CORS.
- `mockup.html` adalah desain konsep asli; dashboard Vue mengadopsi tema & tata letaknya.

[NVIDIA Container Toolkit]: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
