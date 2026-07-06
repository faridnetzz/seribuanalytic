import { Router } from 'express';
import { query } from '../db.js';

const router = Router();

// Daftar kamera + ringkasan jumlah event hari ini (untuk peta sebaran).
router.get('/', async (_req, res, next) => {
  try {
    const { rows } = await query(`
      SELECT c.id, c.name, c.area, c.lat, c.lng, c.modules, c.status, c.last_seen,
             COALESCE(e.today, 0) AS detections_today
      FROM cameras c
      LEFT JOIN (
        SELECT camera_id, count(*) AS today
        FROM detection_events
        WHERE ts >= date_trunc('day', now())
        GROUP BY camera_id
      ) e ON e.camera_id = c.id
      ORDER BY c.id
    `);
    res.json(rows);
  } catch (e) {
    next(e);
  }
});

router.get('/:id', async (req, res, next) => {
  try {
    const { rows } = await query(`SELECT * FROM cameras WHERE id=$1`, [req.params.id]);
    if (!rows.length) return res.status(404).json({ error: 'Kamera tidak ditemukan' });
    res.json(rows[0]);
  } catch (e) {
    next(e);
  }
});

export default router;
