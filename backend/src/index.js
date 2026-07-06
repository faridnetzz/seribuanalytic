import http from 'node:http';
import express from 'express';
import cors from 'cors';
import { config } from './config.js';
import { log } from './logger.js';
import { waitForDb } from './db.js';
import routes from './routes/index.js';
import { attachWebSocket } from './ws/hub.js';
import { startConsumer } from './mqtt/consumer.js';

async function main() {
  const app = express();
  app.use(cors());
  app.use(express.json());

  app.use('/api', routes);

  // Penangan error terpusat
  app.use((err, _req, res, _next) => {
    log.error('API error:', err.message);
    res.status(500).json({ error: 'Kesalahan server internal' });
  });

  const server = http.createServer(app);
  attachWebSocket(server);

  await waitForDb();
  startConsumer();

  server.listen(config.port, () => {
    log.info(`SIGAP backend berjalan di :${config.port}`);
    log.info(`REST  -> http://localhost:${config.port}/api`);
    log.info(`WS    -> ws://localhost:${config.port}/ws`);
  });

  const shutdown = () => {
    log.info('Mematikan server...');
    server.close(() => process.exit(0));
  };
  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);
}

main().catch((e) => {
  log.error('Fatal saat startup:', e.message);
  process.exit(1);
});
