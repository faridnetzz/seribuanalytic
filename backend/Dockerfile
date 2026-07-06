FROM node:20-alpine

WORKDIR /app

# Instal dependensi terlebih dahulu (cache layer)
COPY package.json ./
RUN npm install --omit=dev

# Salin kode sumber
COPY src ./src

ENV NODE_ENV=production
EXPOSE 4000

# Healthcheck sederhana ke endpoint /api/health
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD wget -qO- http://localhost:4000/api/health || exit 1

CMD ["node", "src/index.js"]
