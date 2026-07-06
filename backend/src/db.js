import pg from 'pg';
import { config } from './config.js';
import { log } from './logger.js';

const { Pool } = pg;

export const pool = new Pool({
  connectionString: config.databaseUrl,
  max: 10,
  idleTimeoutMillis: 30_000,
});

pool.on('error', (err) => log.error('PG pool error:', err.message));

export const query = (text, params) => pool.query(text, params);

// Tunggu PostgreSQL siap (saat startup container, DB bisa belum menerima koneksi).
export async function waitForDb(retries = 20, delayMs = 2000) {
  for (let i = 1; i <= retries; i++) {
    try {
      await pool.query('SELECT 1');
      log.info('PostgreSQL terhubung.');
      return;
    } catch (err) {
      log.warn(`PostgreSQL belum siap (${i}/${retries}): ${err.message}`);
      await new Promise((r) => setTimeout(r, delayMs));
    }
  }
  throw new Error('Gagal terhubung ke PostgreSQL setelah beberapa percobaan.');
}
