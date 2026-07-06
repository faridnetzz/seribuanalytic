<script setup>
import { computed } from 'vue';
const props = defineProps({
  segments: { type: Array, default: () => [] }, // [{v:54,c:'var(--ped)'}]
  size: { type: Number, default: 120 },
});
const total = computed(() => props.segments.reduce((s, x) => s + x.v, 0) || 1);
const R = 52;
const C = 2 * Math.PI * R;

const arcs = computed(() => {
  let offset = 0;
  return props.segments.map((s) => {
    const frac = s.v / total.value;
    const dash = `${(frac * C).toFixed(2)} ${(C - frac * C).toFixed(2)}`;
    const arc = { color: s.c, dash, offset: -offset * C };
    offset += frac;
    return arc;
  });
});
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 120 120" class="donut">
    <circle cx="60" cy="60" :r="R" fill="none" stroke="var(--line)" stroke-width="13" />
    <circle v-for="(a, i) in arcs" :key="i" cx="60" cy="60" :r="R" fill="none"
      :stroke="a.color" stroke-width="13" :stroke-dasharray="a.dash"
      :stroke-dashoffset="a.offset" transform="rotate(-90 60 60)" stroke-linecap="butt" />
    <text x="60" y="58" text-anchor="middle" class="d-num">{{ total }}</text>
    <text x="60" y="72" text-anchor="middle" class="d-lbl">TOTAL</text>
  </svg>
</template>

<style scoped>
.donut { flex: none; }
.d-num { font-size: 19px; font-weight: 800; fill: var(--txt); }
.d-lbl { font-size: 8px; fill: var(--txt-faint); letter-spacing: 1.5px; }
</style>
