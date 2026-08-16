FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HWPX_MAX_FILE_BYTES=26214400 \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm fonts-noto-cjk \
    && npm install -g kordoc@4.8.0 --omit=optional \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000
CMD ["sh", "-c", "uvicorn rich_action_ext:app --host 0.0.0.0 --port ${PORT:-10000}"]
