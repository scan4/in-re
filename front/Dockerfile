# 前端构建 + nginx 托管
FROM node:20-alpine AS build
WORKDIR /app

# 先装依赖（利用缓存）
COPY package.json package-lock.json ./
RUN npm ci --silent

# 构建生产产物
COPY . .
RUN npm run build

# ── 运行时：nginx ──
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
