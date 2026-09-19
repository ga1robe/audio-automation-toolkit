# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS base-builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv311-base \
    PATH="/opt/venv311-base/bin:${PATH}"

WORKDIR /workspace
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    build-essential \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv "$VIRTUAL_ENV"
COPY requirements/base.all.txt /tmp/requirements/base.all.txt
RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install --no-cache-dir --prefer-binary -r /tmp/requirements/base.all.txt

FROM python:3.11-slim AS tf-builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv311-tf \
    PATH="/opt/venv311-tf/bin:${PATH}"

WORKDIR /workspace
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    build-essential \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv "$VIRTUAL_ENV"
COPY requirements/tf.all.txt /tmp/requirements/tf.all.txt
RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install --no-cache-dir --prefer-binary -r /tmp/requirements/tf.all.txt

FROM python:3.11-slim AS asr-builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv311-asr \
    PATH="/opt/venv311-asr/bin:${PATH}"

WORKDIR /workspace
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    build-essential \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv "$VIRTUAL_ENV"
COPY requirements/asr.all.txt /tmp/requirements/asr.all.txt
RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install --no-cache-dir --prefer-binary -r /tmp/requirements/asr.all.txt

FROM python:3.11-slim AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VENV_BASE=/opt/venv311-base \
    VENV_TF=/opt/venv311-tf \
    VENV_ASR=/opt/venv311-asr \
    PYTHONPATH=/app/src

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    git \
    libgomp1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=base-builder /opt/venv311-base /opt/venv311-base
COPY --from=tf-builder /opt/venv311-tf /opt/venv311-tf
COPY --from=asr-builder /opt/venv311-asr /opt/venv311-asr
COPY src/ /app/src/

RUN test -x "${VENV_BASE}/bin/python3.11" && \
    test -x "${VENV_TF}/bin/python3.11" && \
    test -x "${VENV_ASR}/bin/python3.11"

ENTRYPOINT ["/opt/venv311-base/bin/python3.11", "/app/src/audio_toolkit.py"]
CMD ["--stage", "full", "--help"]

# Additional specialized targets for smaller single-purpose images:
#   docker build --target base-builder -t audio-toolkit-base .
#   docker build --target tf-builder -t audio-toolkit-tf .
#   docker build --target asr-builder -t audio-toolkit-asr .
#   docker build --target runtime -t audio-toolkit:latest .
