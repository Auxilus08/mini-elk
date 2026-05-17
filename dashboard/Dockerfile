FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_TRANSPORT=poll
ARG VITE_POLL_INTERVAL_MS=5000

ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_TRANSPORT=$VITE_TRANSPORT \
    VITE_POLL_INTERVAL_MS=$VITE_POLL_INTERVAL_MS

RUN npm run build

# -----------------------------------------------------------------------
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://localhost:3000/ || exit 1
