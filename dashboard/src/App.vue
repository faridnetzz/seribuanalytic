<script setup>
import { onMounted } from 'vue';
import Topbar from './components/Topbar.vue';
import Sidebar from './components/Sidebar.vue';
import { useLiveStore } from './stores/live.js';

const live = useLiveStore();
onMounted(() => live.init());
</script>

<template>
  <div class="app">
    <Topbar />
    <Sidebar />
    <main class="main">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style>
.fade-enter-active, .fade-leave-active { transition: opacity 0.25s, transform 0.25s; }
.fade-enter-from { opacity: 0; transform: translateY(8px); }
.fade-leave-to { opacity: 0; }
</style>
