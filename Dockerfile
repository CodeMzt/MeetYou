FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-core.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements-core.txt

COPY . .

EXPOSE 8000

CMD ["python", "-m", "service_runtime"]
