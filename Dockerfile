# Сборка статики прототипа.
FROM node:22-alpine AS build
WORKDIR /app

# Слой зависимостей отдельно: пересобирается только при изменении манифестов.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# Стенд выкладывается только из зелёной сборки: на интервью не везём прототип,
# не прошедший проверки.
RUN npm run typecheck && npm run test -- --run && npm run build

# Отдача статики.
FROM nginx:alpine AS serve
COPY --from=build /app/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
