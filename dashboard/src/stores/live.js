import { defineStore } from 'pinia';
import { api } from '../api/client.js';

const WS_URL =
  import.meta.env.VITE_WS_URL ||
  `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;

// Store realtime: kelola koneksi WS, simpan alert & hitung event masuk.
export const useLiveStore = defineStore('live', {
  state: () => ({
    connected: false,
    alerts: [],          // alert terbaru (maks 50)
    eventCount: 0,       // total event sejak halaman dibuka
    lastEvent: null,
    ws: null,
    reconnectTimer: null,
  }),
  actions: {
    async init() {
      try {
        this.alerts = await api.alerts(20);
      } catch (e) {
        console.warn('Gagal memuat alert awal:', e.message);
      }
      this.connect();
    },
    connect() {
      try {
        const ws = new WebSocket(WS_URL);
        this.ws = ws;
        ws.onopen = () => { this.connected = true; };
        ws.onclose = () => { this.connected = false; this.scheduleReconnect(); };
        ws.onerror = () => ws.close();
        ws.onmessage = (ev) => this.onMessage(JSON.parse(ev.data));
      } catch (e) {
        this.scheduleReconnect();
      }
    },
    scheduleReconnect() {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = setTimeout(() => this.connect(), 3000);
    },
    onMessage(msg) {
      if (msg.type === 'event') {
        this.eventCount += 1;
        this.lastEvent = msg.payload;
      } else if (msg.type === 'alert') {
        this.alerts.unshift(msg.payload);
        this.alerts = this.alerts.slice(0, 50);
      }
    },
    async ack(id) {
      await api.ackAlert(id);
      const a = this.alerts.find((x) => x.id === id);
      if (a) a.acknowledged = true;
    },
  },
});
