# --- Tahap build: kompilasi Vue SPA dengan Vite ---
FROM node:20-alpine AS build
WORKDIR /app

# URL API/WS/STREAM di-bake saat build (dibaca kode browser). Default RELATIF
# (kosong / "/engine") -> nginx dashboard yang proxy ke backend & engine, jadi
# 1 build jalan utk akses lokal (:8080) MAUPUN online (1 hostname via tunnel).
# VITE_WS_URL kosong -> store live.js pakai wss://<host>/ws otomatis (ikut origin).
ARG VITE_API_BASE=
ARG VITE_WS_URL=
ARG VITE_STREAM_BASE=/engine
ENV VITE_API_BASE=$VITE_API_BASE
ENV VITE_WS_URL=$VITE_WS_URL
ENV VITE_STREAM_BASE=$VITE_STREAM_BASE

COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

# --- Tahap serve: nginx statis ---
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
