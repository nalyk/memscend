FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY core ./core
COPY http_gw ./http_gw
COPY mcp_gw ./mcp_gw
COPY config ./config

RUN pip install --upgrade pip \
    && pip install .

CMD ["uvicorn", "http_gw.app:app", "--host", "0.0.0.0", "--port", "8080"]
