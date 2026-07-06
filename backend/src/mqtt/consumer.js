import mqtt from 'mqtt';
import { config } from '../config.js';
import { query, pool } from '../db.js';
import { log } from '../logger.js';
import { broadcast } from '../ws/hub.js';

/**
 * Kontrak pesan MQTT (dipublikasikan simulator / DeepStream nvmsgbroker):
 *
 *   topic: sigap/events/<module>
 *   payload (JSON):
 *   {
 *     "messageId": "uuid",
 *     "ts": "2026-05-22T14:46:00+07:00",
 *     "cameraId": "CAM-01",
 *     "module": "parking",
 *     "eventType": "violation",
 *     "confidence": 0.93,
 *     "data": { ...field spesifik modul... }
 *   }
 */

export function startConsumer() {
  const client = mqtt.connect(config.mqtt.url, {
    reconnectPeriod: 3000,
    clientId: `sigap-backend-${Math.random().toString(16).slice(2, 8)}`,
  });

  client.on('connect', () => {
    log.info(`MQTT terhubung -> ${config.mqtt.url}`);
    client.subscribe(config.mqtt.topic, (err) => {
      if (err) log.error('Gagal subscribe MQTT:', err.message);
      else log.info(`Subscribe topik: ${config.mqtt.topic}`);
    });
  });

  client.on('reconnect', () => log.warn('MQTT mencoba sambung ulang...'));
  client.on('error', (e) => log.error('MQTT error:', e.message));

  client.on('message', async (topic, buf) => {
    let msg;
    try {
      msg = JSON.parse(buf.toString());
    } catch {
      log.warn(`Pesan non-JSON di ${topic} diabaikan.`);
      return;
    }
    try {
      await handleMessage(msg);
    } catch (err) {
      log.error(`Gagal proses event (${msg?.module}):`, err.message);
    }
  });

  return client;
}

async function handleMessage(msg) {
  const { cameraId, module, eventType, confidence, data = {}, ts } = msg;
  if (!cameraId || !module) return;
  const eventTs = ts || new Date().toISOString();
  const et = eventType || 'detection';

  // 1) Log event mentah — KECUALI heartbeat/cleared tumpukan sampah (cegah banjir;
  //    hanya kemunculan pertama 'detection' yg dicatat utk total/kontribusi/heatmap).
  let eventId = null;
  if (!(module === 'waste' && et !== 'detection')) {
    const { rows } = await query(
      `INSERT INTO detection_events (camera_id, module, event_type, confidence, payload, ts)
       VALUES ($1,$2,$3,$4,$5,$6) RETURNING id`,
      [cameraId, module, et, confidence ?? null, data, eventTs]
    );
    eventId = rows[0].id;
  }

  // 2) Tandai kamera aktif
  await query(`UPDATE cameras SET last_seen=$2 WHERE id=$1`, [cameraId, eventTs]);

  // 3) Tulis ke tabel modul + terapkan aturan alert
  let alert = null;
  switch (module) {
    case 'pedestrian':
      await handlePedestrian(cameraId, data, eventTs);
      break;
    case 'waste':
      alert = await handleWaste(cameraId, data, confidence, eventTs, eventId);
      break;
    case 'water':
      alert = await handleWater(cameraId, data, confidence, eventTs, eventId);
      break;
    case 'parking':
      alert = await handleParking(cameraId, data, confidence, eventTs, eventId);
      break;
    default:
      log.warn(`Modul tak dikenal: ${module}`);
  }

  // 4) Siarkan ke dashboard
  broadcast('event', { eventId, cameraId, module, eventType, ts: eventTs, data });
  if (alert) broadcast('alert', alert);
}

// ---- Pedestrian: upsert track (perbarui last_seen + atribut) ----
async function handlePedestrian(cameraId, d, ts) {
  await query(
    `INSERT INTO pedestrian_tracks
       (track_id, global_id, camera_id, attributes, bbox, par_score, reid_score, first_seen, last_seen)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$8)
     ON CONFLICT (camera_id, track_id) DO UPDATE
       SET global_id  = COALESCE(EXCLUDED.global_id, pedestrian_tracks.global_id),
           attributes = EXCLUDED.attributes,
           bbox       = EXCLUDED.bbox,
           par_score  = EXCLUDED.par_score,
           reid_score = EXCLUDED.reid_score,
           last_seen  = EXCLUDED.last_seen`,
    [
      d.trackId ?? Math.floor(Math.random() * 1e9),
      d.globalId ?? null,
      cameraId,
      d.attributes ?? {},
      d.bbox ?? null,
      d.parScore ?? null,
      d.reidScore ?? null,
      ts,
    ]
  );
}

// ---- Waste: TUMPUKAN sebagai EPISODE (occupancy). UPSERT per pile_uid -> 1 baris
//      per tumpukan dari muncul s/d diangkut. Alert sekali bila BELUM DIANGKUT > ambang. ----
async function handleWaste(cameraId, d, confidence, ts, eventId) {
  const vuid = d.pileUid;
  if (!vuid) return null;                       // event lama tanpa pileUid -> abaikan
  const dur = d.durationSeconds ?? 0;

  if (d.status === 'cleared') {                 // tumpukan diangkut/hilang -> tutup episode
    await query(
      `UPDATE waste_piles SET status='cleared', cleared_at=$2, last_seen=$2, duration_seconds=$3
       WHERE pile_uid=$1`, [vuid, ts, dur]
    );
    return null;
  }

  const { rows } = await query(
    `INSERT INTO waste_piles
       (camera_id, pile_uid, severity, area_ratio, bbox, snapshot_url, status,
        first_seen, last_seen, duration_seconds)
     VALUES ($1,$2,$3,$4,$5,$6,'active',$7,$7,$8)
     ON CONFLICT (pile_uid) DO UPDATE
       SET last_seen=$7, duration_seconds=EXCLUDED.duration_seconds,
           severity=EXCLUDED.severity, area_ratio=EXCLUDED.area_ratio,
           bbox=EXCLUDED.bbox, status='active'
     RETURNING (xmax=0) AS inserted, first_seen, alerted`,
    [cameraId, vuid, d.severity ?? 'low', d.areaRatio ?? null, d.bbox ?? null, d.snapshotId ?? vuid, ts, dur]
  );
  const row = rows[0];

  // Alert SEKALI saat tumpukan BELUM DIANGKUT melewati ambang waktu (bukan saat muncul).
  const limit = config.thresholds.wasteNotCollectedS;
  if (dur >= limit && !row.alerted) {
    await query(`UPDATE waste_piles SET alerted=true WHERE pile_uid=$1`, [vuid]);
    const mnt = Math.round(dur / 60);
    return createAlert({
      module: 'waste',
      cameraId,
      severity: dur >= limit * 2 ? 'crit' : 'warn',
      title: `Sampah belum diangkut ${mnt} menit`,
      meta: [`Tingkat: ${d.severity ?? 'low'}`, `Durasi: ${mnt} mnt`],
      eventId,
      ts,
    });
  }
  return null;
}

// ---- Water: simpan reading; alert bila tren naik tajam / status bahaya ----
async function handleWater(cameraId, d, confidence, ts, eventId) {
  await query(
    `INSERT INTO water_levels
       (camera_id, level_m, status, trend_cm_30min, flow_estimate, confidence, ts)
     VALUES ($1,$2,$3,$4,$5,$6,$7)`,
    [
      cameraId,
      d.levelM ?? 0,
      d.status ?? 'aman',
      d.trendCm30min ?? null,
      d.flowEstimate ?? null,
      confidence ?? null,
      ts,
    ]
  );
  const trend = d.trendCm30min ?? 0;
  if (d.status === 'bahaya' || d.status === 'siaga') {
    return createAlert({
      module: 'water',
      cameraId,
      severity: d.status === 'bahaya' ? 'crit' : 'warn',
      title: `Status muka air: ${String(d.status).toUpperCase()} (${d.levelM} m)`,
      meta: [`Tren: ${trend > 0 ? '+' : ''}${trend} cm/30mnt`, `Status: ${d.status}`],
      eventId,
      ts,
    });
  }
  if (trend >= config.thresholds.waterTrendWarnCm) {
    return createAlert({
      module: 'water',
      cameraId,
      severity: 'warn',
      title: `Kenaikan muka air +${trend} cm dalam 30 menit`,
      meta: ['Tren: naik', 'Status: Waspada'],
      eventId,
      ts,
    });
  }
  return null;
}

// ---- Parking: UPSERT 1 baris per pelanggaran (violation_uid) — anti-double.
//      Engine kirim HEARTBEAT tiap ~5s; baris yg sama di-update (dwell+ts) shg
//      "Sedang Aktif" = baris yg ts-nya masih fresh. Alert hanya saat PERTAMA. ----
async function handleParking(cameraId, d, confidence, ts, eventId) {
  const dwell = d.dwellSeconds ?? 0;
  // Tanpa violationId (event lama) -> fallback random supaya tetap tersimpan 1x.
  const vuid = d.violationId || d.snapshotId || `${cameraId}:${d.trackId}:${Date.parse(ts)}`;
  // Kendaraan PERGI -> finalisasi baris (durasi TOTAL + selesai). 1 record/sesi.
  if (d.status === 'cleared') {
    await query(
      `UPDATE parking_violations SET status='cleared', dwell_seconds=$2, ts=$3
       WHERE violation_uid=$1`,
      [vuid, dwell, ts]
    );
    return null;
  }
  const { rows } = await query(
    `INSERT INTO parking_violations
       (camera_id, zone_name, track_id, violation_uid, vehicle_type, plate,
        dwell_seconds, bbox, status, snapshot_url, confidence, started_at, ts)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'active',$9,$10,$11,$11)
     ON CONFLICT (violation_uid) DO UPDATE
       SET dwell_seconds = EXCLUDED.dwell_seconds,
           bbox          = EXCLUDED.bbox,
           status        = 'active',
           ts            = EXCLUDED.ts
     RETURNING (xmax = 0) AS inserted`,
    [
      cameraId,
      d.zoneName ?? null,
      d.trackId ?? null,
      vuid,
      d.vehicleType ?? null,
      d.plate ?? null,
      dwell,
      d.bbox ?? null,
      d.snapshotId ?? null,
      confidence ?? null,
      ts,
    ]
  );
  const isNew = rows[0]?.inserted === true;
  const { parkingDwellWarnS, parkingDwellCritS } = config.thresholds;
  // Alert sekali saja (saat baris baru) -> tidak spam tiap heartbeat.
  if (isNew && dwell >= parkingDwellWarnS) {
    const mnt = Math.round(dwell / 60);
    return createAlert({
      module: 'parking',
      cameraId,
      severity: dwell >= parkingDwellCritS ? 'crit' : 'warn',
      title: `Parkir liar — ${d.vehicleType ?? 'kendaraan'} di ${d.zoneName ?? 'zona terlarang'}`,
      meta: [`Durasi ${mnt} mnt`, `Zona: ${d.zoneName ?? 'Dilarang Parkir'}`],
      eventId,
      ts,
    });
  }
  return null;
}

// ---- Pembuat alert generik ----
async function createAlert({ module, cameraId, severity, title, meta, eventId, ts }) {
  const cam = await pool.query(`SELECT name FROM cameras WHERE id=$1`, [cameraId]);
  const camLabel = `${cameraId} · ${cam.rows[0]?.name ?? ''}`.trim();
  const fullMeta = [camLabel, ...meta];
  const { rows } = await query(
    `INSERT INTO alerts (module, camera_id, severity, title, meta, event_id, ts)
     VALUES ($1,$2,$3,$4,$5,$6,$7)
     RETURNING id, module, camera_id AS "cameraId", severity, title, meta, ts`,
    [module, cameraId, severity, title, JSON.stringify(fullMeta), eventId, ts]
  );
  return rows[0];
}
