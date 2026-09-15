FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

ENV VENV_BASE=/opt/venv311-base
ENV VENV_TF=/opt/venv311-tf
ENV VENV_ASR=/opt/venv311-asr

RUN /usr/bin/apt-get update && /usr/bin/apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    python3-pip \
    ffmpeg \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements/ /app/requirements/

RUN /usr/bin/python3.11 -m venv "${VENV_BASE}" && \
    "${VENV_BASE}/bin/python" -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    "${VENV_BASE}/bin/python" -m pip install --no-cache-dir \
        -r /app/requirements/base.all.txt

RUN /usr/bin/python3.11 -m venv "${VENV_TF}" && \
    "${VENV_TF}/bin/python" -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    "${VENV_TF}/bin/python" -m pip install --no-cache-dir \
        -r /app/requirements/tf.all.txt

RUN /usr/bin/python3.11 -m venv "${VENV_ASR}" && \
    "${VENV_ASR}/bin/python" -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    "${VENV_ASR}/bin/python" -m pip install --no-cache-dir \
        -r /app/requirements/asr.all.txt

COPY src/ /app/src/

RUN test -x "${VENV_BASE}/bin/python3.11" && \
    test -x "${VENV_TF}/bin/python3.11" && \
    test -x "${VENV_ASR}/bin/python3.11" && \
    test -x "${VENV_BASE}/bin/spleeter"

ENTRYPOINT ["/opt/venv311-base/bin/python3.11", "/app/src/audio_toolkit.py"]

CMD ["--help"]
