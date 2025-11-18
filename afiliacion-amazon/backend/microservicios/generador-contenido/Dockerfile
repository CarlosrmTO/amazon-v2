FROM mirror.gcr.io/library/python:3.11-slim
ARG BUILD_ID=redeploy-20251118-1830
ENV BUILD_ID=${BUILD_ID}
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8010
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8010}"]
