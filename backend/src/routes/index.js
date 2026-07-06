import { Router } from 'express';
import { pool } from '../db.js';
import cameras from './cameras.js';
import overview from './overview.js';
import alerts from './alerts.js';
import pedestrian from './pedestrian.js';
import waste from './waste.js';
import water from './water.js';
import parking from './parking.js';

const router = Router();

router.get('/health', async (_req, res) => {
  try {
    await pool.query('SELECT 1');
    res.json({ status: 'ok', db: 'up', ts: new Date().toISOString() });
  } catch (e) {
    res.status(503).json({ status: 'degraded', db: 'down', error: e.message });
  }
});

router.use('/cameras', cameras);
router.use('/overview', overview);
router.use('/alerts', alerts);
router.use('/pedestrian', pedestrian);
router.use('/waste', waste);
router.use('/water', water);
router.use('/parking', parking);

export default router;
