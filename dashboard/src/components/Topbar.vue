<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue';
import { useLiveStore } from '../stores/live.js';

const live = useLiveStore();
const clock = ref('');
let timer;

const tick = () => {
  clock.value = new Date().toLocaleTimeString('id-ID', {
    timeZone: 'Asia/Jakarta',
    hour12: false,
  });
};
onMounted(() => { tick(); timer = setInterval(tick, 1000); });
onUnmounted(() => clearInterval(timer));

const status = computed(() => (live.connected ? 'LIVE' : 'OFFLINE'));
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <div class="logo"></div>
      <div>
        <h1>SIGAP</h1>
        <div class="sub">Analitik Pengawasan</div>
      </div>
    </div>
    <div class="spacer"></div>

    <div class="topbar-stat">
      <b>{{ live.eventCount.toLocaleString('id-ID') }}</b>
      <span>Event Sesi Ini</span>
    </div>

    <div class="live-clock">
      <span class="dot-live" :class="{ off: !live.connected }"></span>
      <span class="mono">{{ status }} · {{ clock }} WIB</span>
    </div>

    <div class="gov-tag">
      <b>Pemkot Bandar Lampung</b><br />Pusat Komando SIGAP
    </div>
  </header>
</template>

<style scoped>
.topbar {
  grid-column: 1 / 3;
  display: flex; align-items: center; gap: 18px; padding: 0 22px;
  background: linear-gradient(180deg, #ffffff, #f8fafc);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(8px);
}
.brand { display: flex; align-items: center; gap: 13px; }
.logo {
  width: 34px; height: 34px; border-radius: 9px; position: relative;
  background: conic-gradient(from 140deg, var(--ped), var(--water), var(--park), var(--waste), var(--ped));
  box-shadow: 0 0 22px -4px rgba(14,165,233, 0.6);
}
.logo::after { content: ''; position: absolute; inset: 3px; border-radius: 6px; background: var(--bg-2); }
.brand h1 { font-size: 16px; font-weight: 800; letter-spacing: 0.5px; line-height: 1; }
.brand .sub { font-size: 10px; color: var(--txt-faint); letter-spacing: 2.5px; font-weight: 600; margin-top: 3px; text-transform: uppercase; }
.spacer { flex: 1; }
.live-clock { display: flex; align-items: center; gap: 9px; font-size: 13px; color: var(--txt-dim); }
.dot-live { width: 8px; height: 8px; border-radius: 50%; background: var(--crit); box-shadow: 0 0 0 0 rgba(228,0,20, 0.6); animation: pulse 2s infinite; }
.dot-live.off { background: var(--txt-faint); animation: none; }
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(228,0,20, 0.55); }
  70% { box-shadow: 0 0 0 9px rgba(228,0,20, 0); }
  100% { box-shadow: 0 0 0 0 rgba(228,0,20, 0); }
}
.topbar-stat { display: flex; flex-direction: column; align-items: flex-end; padding: 0 16px; border-left: 1px solid var(--line-soft); }
.topbar-stat b { font-size: 15px; font-weight: 700; }
.topbar-stat span { font-size: 9.5px; color: var(--txt-faint); letter-spacing: 1.5px; text-transform: uppercase; margin-top: 2px; }
.gov-tag { font-size: 10px; color: var(--txt-faint); text-align: right; line-height: 1.4; }
.gov-tag b { color: var(--txt-dim); font-weight: 600; }
</style>
