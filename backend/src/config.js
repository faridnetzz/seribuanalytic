// Konfigurasi terpusat — semua dari environment dengan default aman untuk dev.

export const config = {
  port: parseInt(process.env.PORT || '4000', 10),
  databaseUrl:
    process.env.DATABASE_URL ||
    'postgres://sigap:sigap_secret@localhost:5432/sigap',
  mqtt: {
    url: process.env.MQTT_URL || 'mqtt://localhost:1883',
    // Hanya dengar event final per modul. Output mentah DeepStream ada di
    // sigap/perception/# dan dikonsumsi oleh engine, bukan backend.
    topic: process.env.MQTT_TOPIC || 'sigap/events/#',
  },
  // Ambang aturan alert (lihat mqtt/consumer.js)
  thresholds: {
    parkingDwellWarnS: 300, // > 5 menit -> warn
    parkingDwellCritS: 600, // > 10 menit -> crit
    waterTrendWarnCm: 10, // kenaikan > 10 cm / 30 mnt -> warn
    wasteCriticalSeverity: 'critical',
    wasteNotCollectedS: parseInt(process.env.WASTE_NOT_COLLECTED_S || '1800', 10), // tumpukan belum diangkut > 30 mnt -> alert
  },
  // Kontak pihak berwenang utk tombol lapor (dashboard buka wa.me). GANTI dgn nomor asli.
  contacts: {
    dishubWa: process.env.DISHUB_WA || '6281234567890',
    dishubName: process.env.DISHUB_NAME || 'Dishub Kota Bandar Lampung',
    dlhWa: process.env.DLH_WA || '6281234567890',
    dlhName: process.env.DLH_NAME || 'DLH / Petugas Kebersihan Bandar Lampung',
  },
  // Endpoint IP speaker command center (placeholder; isi saat perangkat terpasang).
  speaker: {
    baseUrl: process.env.SPEAKER_BASE_URL || '', // mis. http://10.0.0.50/api/announce
  },
};
