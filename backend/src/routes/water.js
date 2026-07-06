import { Router } from 'express';
import { query } from '../db.js';

const router = Router();

// Pembacaan terbaru per kamera sungai + status.
router.get('/summary', async (_req, res, next) => {
  try {
    const accuracy = await scalar(`SELECT accuracy FROM modules WHERE code='water'`);
    const { rows } = await query(`
      SELECT DISTINCT ON (camera_id)
             w.camera_id AS "cameraId", c.name AS "cameraName", c.area,
             w.level_m AS "levelM", w.status, w.trend_cm_30min AS "trendCm30min",
             w.flow_estimate AS "flowEstimate", w.confidence, w.ts
      FROM water_levels w
      JOIN cameras c ON c.id = w.camera_id
      ORDER BY camera_id, ts DESC
    `);
    res.json({ accuracy, stations: rows });
  } catch (e) {
    next(e);
  }
});

// Deret waktu ketinggian air untuk satu kamera (grafik tren).
router.get('/series', async (req, res, next) => {
  try {
    const camera = req.query.camera;
    const hours = Math.min(parseInt(req.query.hours || '24', 10), 168);
    if (!camera) return res.status(400).json({ error: 'Parameter camera wajib diisi' });
    const { rows } = await query(
      `SELECT level_m AS "levelM", status, ts
       FROM water_levels
       WHERE camera_id = $1 AND ts >= now() - ($2 || ' hours')::interval
       ORDER BY ts ASC`,
      [camera, String(hours)]
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
