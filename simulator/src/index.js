// =====================================================================
// SIGAP Simulator — meniru output DeepStream nvmsgbroker.
// Mempublikasikan event 4 modul ke MQTT supaya backend + dashboard
// bisa diuji penuh tanpa GPU. Format pesan == kontrak consumer backend.
// =====================================================================
import mqtt from 'mqtt';

const MQTT_URL = process.env.MQTT_URL || 'mqtt://localhost:1883';
const INTERVAL = parseInt(process.env.EVENT_INTERVAL_MS || '1500', 10);

// Peta kamera -> modul (selaras dengan db/init/02_seed.sql)
const CAMERAS = {
  'CAM-01': ['parking', 'pedestrian'],
  'CAM-02': ['waste', 'pedestrian'],
  'CAM-03': ['water', 'waste'],
  'CAM-04': ['parking'],
  'CAM-05': ['pedestrian', 'parking'],
  'CAM-06': ['water'],
  'CAM-07': ['pedestrian'],
  'CAM-08': ['pedestrian', 'waste'],
};

const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
const rnd = (min, max) => Math.random() * (max - min) + min;
const chance = (p) => Math.random() < p;
const round = (v, d = 2) => Math.round(v * 10 ** d) / 10 ** d;

// --- State yang menetap antar tick ---
const waterState = { 'CAM-03': 0.84, 'CAM-06': 1.35 };
let trackSeq = 2200; // ID track pedestrian berjalan
let globalSeq = 9000; // ID global ReID

// ---------------- Generator per modul ----------------
function genPedestrian(cameraId) {
  trackSeq += 1;
  const gender = chance(0.62) ? 'pria' : 'wanita';
  return {
    eventType: 'track',
    confidence: round(rnd(0.85, 0.99), 3),
    data: {
      trackId: trackSeq,
      // Sebagian track cocok lintas-kamera (ReID)
      globalId: chance(0.4) ? ++globalSeq : null,
      attributes: {
        gender,
        ageGroup: pick(['anak', 'dewasa', 'dewasa', 'lansia']),
        upperColor: pick(['gelap', 'terang', 'merah', 'biru']),
        helmet: chance(0.71),
        bag: chance(0.44),
        rider: chance(0.67),
        footwear: pick(['sepatu', 'sandal']),
      },
      bbox: { x: round(rnd(0.05, 0.8)), y: round(rnd(0.3, 0.5)), w: round(rnd(0.06, 0.1)), h: round(rnd(0.25, 0.35)) },
      parScore: round(rnd(0.9, 0.99), 3),
      reidScore: round(rnd(0.82, 0.97), 3),
    },
  };
}

function genWaste() {
  const severity = pick(['low', 'low', 'medium', 'medium', 'high', 'critical']);
  return {
    eventType: 'detection',
    confidence: round(rnd(0.8, 0.96), 3),
    data: {
      severity,
      volumeLevel: pick(['kecil', 'sedang', 'besar']),
      areaRatio: round(rnd(0.01, 0.18), 4),
      isFloating: chance(0.25),
      bbox: { x: round(rnd(0.1, 0.7)), y: round(rnd(0.4, 0.7)), w: round(rnd(0.1, 0.25)), h: round(rnd(0.1, 0.2)) },
    },
  };
}

function genWater(cameraId) {
  // Random walk ketinggian air, kadang lonjakan
  const prev = waterState[cameraId] ?? 0.8;
  const delta = chance(0.15) ? rnd(0.05, 0.18) : rnd(-0.03, 0.04);
  const level = Math.max(0.2, round(prev + delta, 3));
  waterState[cameraId] = level;
  const trendCm = round((level - prev) * 100, 1);

  let status = 'aman';
  if (level >= 2.0) status = 'bahaya';
  else if (level >= 1.5) status = 'siaga';
  else if (level >= 1.1) status = 'waspada';

  return {
    eventType: 'reading',
    confidence: round(rnd(0.9, 0.97), 3),
    data: {
      levelM: level,
      status,
      trendCm30min: trendCm,
      flowEstimate: round(level * rnd(8, 14), 1),
    },
  };
}

function genParking() {
  const vehicleType = pick(['motor', 'mobil', 'pickup', 'truk']);
  // Dwell bervariasi; sebagian melewati ambang sehingga memicu alert
  const dwellSeconds = Math.round(pick([45, 90, 150, 320, 420, 650, 1020]));
  return {
    eventType: 'violation',
    confidence: round(rnd(0.85, 0.98), 3),
    data: {
      zoneName: pick(['Dilarang Parkir — Badan Jalan', 'Marka Kuning', 'Zona Pejalan Kaki']),
      vehicleType,
      dwellSeconds,
      status: chance(0.85) ? 'active' : 'cleared',
      bbox: { x: round(rnd(0.1, 0.7)), y: round(rnd(0.55, 0.8)), w: round(rnd(0.1, 0.2)), h: round(rnd(0.1, 0.18)) },
    },
  };
}

const GENERATORS = {
  pedestrian: genPedestrian,
  waste: genWaste,
  water: genWater,
  parking: genParking,
};

// ---------------- Loop publikasi ----------------
const client = mqtt.connect(MQTT_URL, { reconnectPeriod: 3000 });

client.on('connect', () => {
  console.log(`[simulator] terhubung ke ${MQTT_URL}, interval ${INTERVAL}ms`);
  setInterval(tick, INTERVAL);
});
client.on('error', (e) => console.error('[simulator] MQTT error:', e.message));

function tick() {
  // Pilih satu kamera acak, lalu satu modul aktif padanya
  const cameraId = pick(Object.keys(CAMERAS));
  const module = pick(CAMERAS[cameraId]);

  // Modul air & sampah tidak perlu sepadat pedestrian
  if (module === 'water' && !chance(0.5)) return;
  if (module === 'waste' && !chance(0.6)) return;
  if (module === 'parking' && !chance(0.5)) return;

  const gen = GENERATORS[module](cameraId);
  const msg = {
    messageId: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    ts: new Date().toISOString(),
    cameraId,
    module,
    ...gen,
  };
  client.publish(`sigap/events/${module}`, JSON.stringify(msg), { qos: 0 });
}
