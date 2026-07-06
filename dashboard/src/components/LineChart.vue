<script setup>
import { computed } from 'vue';
const props = defineProps({
  series: { type: Array, default: () => [] },
  labels: { type: Array, default: () => [] },
  accent: { type: String, default: 'var(--water)' },
  width: { type: Number, default: 560 },
  height: { type: Number, default: 185 },
});

const pad = { l: 6, r: 6, t: 10, b: 18 };
const max = computed(() => Math.max(1, ...props.series));

const points = computed(() => {
  const n = props.series.length;
  if (!n) return '';
  const w = props.width - pad.l - pad.r;
  const h = props.height - pad.t - pad.b;
  return props.series
    .map((v, i) => {
      const x = pad.l + (n === 1 ? 0 : (i / (n - 1)) * w);
      const y = pad.t + h - (v / max.value) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
});

const area = computed(() => {
  if (!points.value) return '';
  const h = props.height - pad.b;
  const first = points.value.split(' ')[0].split(',')[0];
  const last = points.value.split(' ').at(-1).split(',')[0];
  return `${first},${h} ${points.value} ${last},${h}`;
});
</script>

<template>
  <svg :viewBox="`0 0 ${width} ${height}`" class="line-chart" preserveAspectRatio="none">
    <defs>
      <linearGradient :id="`g-${accent}`" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" :stop-color="accent" stop-opacity="0.28" />
        <stop offset="100%" :stop-color="accent" stop-opacity="0" />
      </linearGradient>
    </defs>
    <polygon :points="area" :fill="`url(#g-${accent})`" />
    <polyline :points="points" :stroke="accent" fill="none" stroke-width="2"
      stroke-linejoin="round" stroke-linecap="round" />
    <text v-for="(l, i) in labels" :key="i" v-show="l"
      :x="pad.l + (labels.length <= 1 ? 0 : (i / (labels.length - 1)) * (width - pad.l - pad.r))"
      :y="height - 4" class="lbl" text-anchor="middle">{{ l }}</text>
  </svg>
</template>

<style scoped>
.line-chart { width: 100%; height: auto; display: block; }
.lbl { font-size: 8.5px; fill: var(--txt-faint); font-family: 'JetBrains Mono', monospace; }
</style>
