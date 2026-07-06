import { Router } from 'express';
import { query } from '../db.js';

const router = Router();

router.get('/summary', async (_req, res, next) => {
  try {
    const active = await scalar(
      `SELECT count(*) FROM pedestrian_tracks WHERE last_seen >= now() - interval '30 seconds'`
    );
    const uniqueToday = await scalar(
      `SELECT count(DISTINCT COALESCE(global_id, id)) FROM pedestrian_tracks
       WHERE last_seen >= date_trunc('day', now())`
    );
    const accuracy = await scalar(`SELECT accuracy FROM modules WHERE code='pedestrian'`);
    const reid = await scalar(
      `SELECT COALESCE(round(avg(reid_score)*100, 1), 0) FROM pedestrian_tracks
       WHERE reid_score IS NOT NULL AND last_seen >= date_trunc('day', now())`
    );
    const attributes = await attributeDistribution();
    res.json({
      activeTracked: active,
      uniqueToday,
      parAccuracy: accuracy,
      reidMatchRate: reid,
      attributes,
    });
  } catch (e) {
    next(e);
  }
});

// Hapus track (dipanggil saat snapshot orang dihapus dari galeri) -> datanya
// hilang dari distribusi atribut & hitungan. Tanpa trackId: tak melakukan apa-apa.
router.post('/track/delete', async (req, res, next) => {
  try {
    const { cameraId, trackId } = req.body || {};
    if (!cameraId || trackId == null) {
      return res.status(400).json({ ok: false, error: 'cameraId & trackId wajib' });
    }
    const { rowCount } = await query(
      `DELETE FROM pedestrian_tracks WHERE camera_id = $1 AND track_id = $2`,
      [cameraId, trackId]
    );
    res.json({ ok: true, deleted: rowCount });
  } catch (e) {
    next(e);
  }
});

router.get('/tracks', async (req, res, next) => {
  try {
    const limit = Math.min(parseInt(req.query.limit || '50', 10), 200);
    const camera = req.query.camera;
    const params = [];
    let where = '';
    if (camera) {
      params.push(camera);
      where = `WHERE camera_id = $1`;
    }
    params.push(limit);
    const { rows } = await query(
      `SELECT id, track_id AS "trackId", global_id AS "globalId", camera_id AS "cameraId",
              attributes, bbox, par_score AS "parScore", reid_score AS "reidScore",
              first_seen AS "firstSeen", last_seen AS "lastSeen"
       FROM pedestrian_tracks ${where}
       ORDER BY last_seen DESC LIMIT $${params.length}`,
      params
    );
    res.json(rows);
  } catch (e) {
    next(e);
  }
});

// Distribusi atribut (persentase) dari track hari ini.
async function attributeDistribution() {
  const { rows } = await query(`
    SELECT attributes FROM pedestrian_tracks
    WHERE last_seen >= date_trunc('day', now())
  `);
  if (!rows.length) return [];
  const total = rows.length;                 // PEMBAGI = total track hari ini
  const counters = {};
  for (const r of rows) {
    const a = r.attributes || {};
    for (const [k, v] of Object.entries(a)) {
      // Lewati nilai numerik (mis. age) — distribusi kategorikal saja.
      if (k === 'age' || (typeof v !== 'string' && typeof v !== 'boolean')) continue;
      const key = `${k}:${v}`;
      counters[key] = (counters[key] || 0) + 1;
    }
  }
  // Persen DARI TOTAL track (bukan dari yg punya atribut itu) -> tak lagi selalu 100%
  // utk atribut boolean (mis. topi yg cuma muncul saat true).
  return Object.entries(counters)
    .map(([key, count]) => {
      const [attr] = key.split(':');
      return { key, attr, pct: Math.round((count / total) * 100) };
    })
    .sort((a, b) => b.pct - a.pct)
    .slice(0, 8);
}

async function scalar(sql, params) {
  const { rows } = await query(sql, params);
  return Number(Object.values(rows[0])[0]);
}

export default router;
