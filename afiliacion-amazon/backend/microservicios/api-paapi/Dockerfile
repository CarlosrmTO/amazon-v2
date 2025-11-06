FROM python:3.11-slim
ARG BUILD_ID=local
ENV BUILD_ID=${BUILD_ID}
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY afiliacion-amazon/backend/microservicios/api-paapi/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY afiliacion-amazon/backend/microservicios/api-paapi/ ./
EXPOSE 8000
# Bind to Railway's PORT if provided
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
