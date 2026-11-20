FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data

# Data (SQLite + encryption key) lives in /app/data — mount a volume over it.
VOLUME ["/app/data"]

ENV DATA_DIR=/app/data
ENV PORT=7000

EXPOSE 7000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7000}"]
