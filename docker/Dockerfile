FROM python:3.11-slim

ARG REQUIREMENTS_FILE=requirements/base.all.txt

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/src

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements ./requirements

RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r "${REQUIREMENTS_FILE}"

COPY . .

CMD ["sleep", "infinity"]