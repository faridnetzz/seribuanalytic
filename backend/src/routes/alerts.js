import { Router } from 'express';
import { query } from '../db.js';

const router = Router();

// Aliran alert terkini lintas modul.
router.get('/', async (req, res, next) => {
  try {
    const limit = Math.min(parseInt(req.query.limit || '20', 10), 100);
    const severity = req.query.severity; // info | warn | crit (opsional)
    const params = [];
    let where = '';
    if (severity) {
      params.push(severity);
      where = `WHERE severity = $1`;
    }
    params.push(limit);
    const { rows } = await query(
      `SELECT id, module, camera_id AS "cameraId", severity, title, meta,
              acknowledged, ts
       FROM alerts ${where}
       ORDER BY ts DESC
       LIMIT $${params.length}`,
      params
    );
    res.json(rows);
  } catch (e) {
    next(e);
  }
});

// Tandai alert sudah ditindak.
router.post('/:id/ack', async (req, res, next) => {
  try {
    const { rows } = await query(
      `UPDATE alerts SET acknowledged=true, acknowledged_by=$2
       WHERE id=$1 RETURNING id, acknowledged`,
      [req.params.id, req.body?.by ?? 'operator']
    );
    if (!rows.length) return res.status(404).json({ error: 'Alert tidak ditemukan' });
    res.json(rows[0]);
  } catch (e) {
    next(e);
  }
});

export default router;
