import { WebSocketServer } from 'ws';
import { log } from '../logger.js';

let wss = null;

// Pasang WebSocket server pada HTTP server yang sama (path /ws).
export function attachWebSocket(server) {
  wss = new WebSocketServer({ server, path: '/ws' });

  wss.on('connection', (ws) => {
    log.info(`WS klien tersambung (total: ${wss.clients.size})`);
    ws.send(JSON.stringify({ type: 'hello', ts: new Date().toISOString() }));

    ws.on('close', () =>
      log.info(`WS klien terputus (sisa: ${wss.clients.size})`)
    );
    ws.on('error', (e) => log.warn('WS error:', e.message));
  });

  // Ping berkala agar koneksi mati tidak menumpuk.
  setInterval(() => {
    if (!wss) return;
    for (const c of wss.clients) {
      if (c.readyState === c.OPEN) c.ping();
    }
  }, 30_000);

  return wss;
}

// Siarkan pesan ke semua klien. type contoh: 'event' | 'alert'.
export function broadcast(type, payload) {
  if (!wss) return;
  const msg = JSON.stringify({ type, payload, ts: new Date().toISOString() });
  for (const c of wss.clients) {
    if (c.readyState === c.OPEN) c.send(msg);
  }
}
