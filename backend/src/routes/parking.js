import { Router } from 'express';
import { query } from '../db.js';
import { config } from '../config.js';
import { log } from '../logger.js';

const router = Router();

router.get('/summary', async (_req, res, next) => {
  try {
    // 1 baris = 1 pelanggaran (upsert by violation_uid) -> hitung pakai started_at.
    const today = await scalar(
      `SELECT count(*) FROM parking_violations WHERE started_at >= date_trunc('day', now())`
    );
    // "Sedang aktif" = pelanggaran yg masih DIPERBARUI engine (heartbeat <45s) ->
    // kendaraan benar2 masih di zona saat ini. Tahan thd engine restart (auto-luruh).
    const active = await scalar(
      `SELECT count(*) FROM parking_violations
       WHERE status='active' AND ts >= now() - interval '45 seconds'`
    );
    const zones = await scalar(`SELECT count(*) FROM parking_zones`);
    const accuracy = await scalar(`SELECT accuracy FROM modules WHERE code='parking'`);
    const avgDwell = await scalar(
      `SELECT COALESCE(round(avg(dwell_seconds)), 0) FROM parking_violations
       WHERE started_at >= date_trunc('day', now())`
    );
    const byVehicle = await query(`
      SELECT COALESCE(vehicle_type, 'lainnya') AS "vehicleType", count(*)::int AS total
      FROM parking_violations
      WHERE started_at >= date_trunc('day', now())
      GROUP BY 1 ORDER BY total DESC
    `);
    res.json({
      today,
      active,
      zones,
      accuracy,
      avgDwellSeconds: avgDwell,
      byVehicle: byVehicle.rows,
      contacts: { dishubWa: config.contacts.dishubWa, dishubName: config.contacts.dishubName },
    });
  } catch (e) {
    next(e);
  }
});

// Hapus 1 pelanggaran (violation_uid = sid snapshot) — dipanggil saat foto dihapus.
router.post('/violation/delete', async (req, res, next) => {
  try {
    const { violationId } = req.body || {};
    if (!violationId) return res.status(400).json({ ok: false, error: 'violationId wajib' });
    const { rowCount } = await query(
      `DELETE FROM parking_violations WHERE violation_uid = $1`, [violationId]
    );
    res.json({ ok: true, deleted: rowCount });
  } catch (e) {
    next(e);
  }
});

// Hapus SEMUA pelanggaran parkir.
router.post('/violations/clear', async (_req, res, next) => {
  try {
    const { rowCount } = await query(`DELETE FROM parking_violations`);
    res.json({ ok: true, deleted: rowCount });
  } catch (e) {
    next(e);
  }
});

// Peringatan via IP speaker command center (placeholder; siap diisi perangkat).
router.post('/speaker', async (req, res, next) => {
  try {
    const { cameraId, message } = req.body || {};
    if (!cameraId) return res.status(400).json({ ok: false, error: 'cameraId wajib' });
    const text = message || 'Mohon perhatian, Anda parkir di zona terlarang. Segera pindahkan kendaraan Anda.';
    // TODO: integrasi nyata -> HTTP ke speaker IP (config.speaker.baseUrl) per kamera.
    log.info(`[speaker] CAM ${cameraId}: "${text}" (baseUrl=${config.speaker.baseUrl || 'belum diset'})`);
    res.json({ ok: true, cameraId, delivered: Boolean(config.speaker.baseUrl), message: text });
  } catch (e) {
    next(e);
  }
});

router.get('/violations', async (req, res, next) => {
  try {
    const limit = Math.min(parseInt(req.query.limit || '30', 10), 100);
    const status = req.query.status;
    const params = [];
    let where = '';
    if (status) {
      params.push(status);
      where = `WHERE v.status = $1`;
    }
    params.push(limit);
    const { rows } = await query(
      `SELECT v.id, v.camera_id AS "cameraId", c.name AS "cameraName", c.area,
              v.zone_name AS "zoneName", v.vehicle_type AS "vehicleType", v.plate,
              v.track_id AS "trackId", v.snapshot_url AS "snapshotId",
              v.dwell_seconds AS "dwellSeconds", v.status, v.confidence, v.ts
       FROM parking_violations v
       JOIN cameras c ON c.id = v.camera_id
       ${where}
       ORDER BY v.ts DESC LIMIT $${params.length}`,
      params
    );
    res.json(rows);
  } catch (e) {
    next(e);
  }
});

async function scalar(sql, params) {
  const { rows } = await query(sql, params);
  return Number(Object.values(rows[0])[0]);
}

export default router;
