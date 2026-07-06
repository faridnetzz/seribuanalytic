import { createRouter, createWebHistory } from 'vue-router';
import Overview from '../views/Overview.vue';

const routes = [
  { path: '/', name: 'overview', component: Overview, meta: { title: 'Ringkasan Kota' } },
  {
    path: '/pedestrian',
    name: 'pedestrian',
    component: () => import('../views/Pedestrian.vue'),
    meta: { title: 'Pedestrian Tracking' },
  },
  {
    path: '/waste',
    name: 'waste',
    component: () => import('../views/Waste.vue'),
    meta: { title: 'Deteksi Sampah' },
  },
  {
    path: '/water',
    name: 'water',
    component: () => import('../views/Water.vue'),
    meta: { title: 'Debit Air Sungai' },
  },
  {
    path: '/parking',
    name: 'parking',
    component: () => import('../views/Parking.vue'),
    meta: { title: 'Parkir Liar' },
  },
];

export default createRouter({
  history: createWebHistory(),
  routes,
});
