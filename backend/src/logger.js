// Logger minimalis berstempel waktu (zona Asia/Jakarta).
const fmt = () =>
  new Date().toLocaleString('id-ID', { timeZone: 'Asia/Jakarta', hour12: false });

export const log = {
  info: (...a) => console.log(`[${fmt()}] [info]`, ...a),
  warn: (...a) => console.warn(`[${fmt()}] [warn]`, ...a),
  error: (...a) => console.error(`[${fmt()}] [error]`, ...a),
};
