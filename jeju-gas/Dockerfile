# 1) 프론트엔드 빌드
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# 2) 백엔드 + 정적 프론트 서빙
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ ./backend/
COPY --from=web /web/dist ./frontend/dist
WORKDIR /app/backend
ENV FRONTEND_DIST=/app/frontend/dist \
    DATABASE_URL=sqlite:////data/jeju_gas.db
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
