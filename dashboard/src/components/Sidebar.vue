<script setup>
import { useLiveStore } from '../stores/live.js';
const live = useLiveStore();

const nav = [
  { to: '/', label: 'Ringkasan Kota', acc: 'var(--water)' },
];
const modules = [
  { to: '/pedestrian', label: 'Pedestrian Tracking', acc: 'var(--ped)' },
  { to: '/waste', label: 'Deteksi Sampah', acc: 'var(--waste)' },
  { to: '/water', label: 'Debit Air Sungai', acc: 'var(--water)' },
  { to: '/parking', label: 'Parkir Liar', acc: 'var(--park)' },
];
</script>

<template>
  <aside class="sidebar">
    <div class="nav-label">Pusat Kendali</div>
    <router-link v-for="n in nav" :key="n.to" :to="n.to" class="nav-item"
      :style="{ '--acc': n.acc }" active-class="active" exact-active-class="active">
      <span class="dot" :style="{ background: n.acc }"></span>{{ n.label }}
    </router-link>

    <div class="nav-label">Modul Analitik AI</div>
    <router-link v-for="m in modules" :key="m.to" :to="m.to" class="nav-item"
      :style="{ '--acc': m.acc }" active-class="active">
      <span class="dot" :style="{ background: m.acc }"></span>{{ m.label }}
    </router-link>

    <div class="grow"></div>

    <div class="nav-label">Status Sistem</div>
    <div class="sys-box">
      <div class="sys-row"><span>Koneksi Live</span><b :style="{ color: live.connected ? 'var(--ok)' : 'var(--crit)' }">
        {{ live.connected ? 'Tersambung' : 'Terputus' }}</b></div>
      <div class="sys-row"><span>Event Sesi</span><b>{{ live.eventCount.toLocaleString('id-ID') }}</b></div>
      <div class="sys-row"><span>Alert Aktif</span><b>{{ live.alerts.length }}</b></div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  grid-column: 1; grid-row: 2;
  background: linear-gradient(180deg, var(--bg-2), var(--bg));
  border-right: 1px solid var(--line);
  padding: 18px 12px; display: flex; flex-direction: column; gap: 5px; overflow-y: auto;
}
.nav-label { font-size: 9.5px; letter-spacing: 2px; color: var(--txt-faint); text-transform: uppercase; font-weight: 700; padding: 10px 12px 6px; }
.nav-item {
  display: flex; align-items: center; gap: 12px; padding: 11px 12px; border-radius: 11px;
  cursor: pointer; color: var(--txt-dim); font-size: 13.5px; font-weight: 500;
  border: 1px solid transparent; transition: all 0.18s ease; position: relative;
}
.nav-item:hover { background: var(--panel); color: var(--txt); }
.nav-item.active { background: var(--panel-2); color: var(--txt); border-color: var(--line); }
.nav-item.active::before {
  content: ''; position: absolute; left: 0; top: 50%; transform: translateY(-50%);
  width: 3px; height: 20px; border-radius: 0 3px 3px 0; background: var(--acc);
}
.dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
.grow { flex: 1; }
.sys-box { padding: 13px; border-radius: 12px; background: var(--panel); border: 1px solid var(--line-soft); }
.sys-row { display: flex; justify-content: space-between; align-items: center; font-size: 11px; margin-bottom: 9px; }
.sys-row:last-child { margin-bottom: 0; }
.sys-row span { color: var(--txt-faint); }
.sys-row b { font-weight: 600; color: var(--txt-dim); }
</style>
