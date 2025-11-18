FROM mirror.gcr.io/library/python:3.11-slim
ARG BUILD_ID=redeploy-20251118-1108
ENV BUILD_ID=${BUILD_ID}
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# Bind to Railway's PORT; enable proxy headers and access logs for debugging
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*' --access-log"]
