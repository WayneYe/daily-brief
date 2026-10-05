# CI runner: uv deps, ffmpeg, Kokoro weights baked in (~under GHCR free tier when possible).
FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/daily-brief

ENV UV_NO_DEV=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/opt/daily-brief/.venv \
    PATH="/opt/daily-brief/.venv/bin:${PATH}" \
    HF_HOME=/root/.cache/huggingface

COPY pyproject.toml ./

# pyproject.toml points at a private index locally; public image builds use PyPI.
RUN uv sync --no-install-project --default-index https://pypi.org/simple

# Warm Hugging Face cache so scheduled runs skip model downloads.
RUN uv run python -c "from kokoro import KPipeline; KPipeline(lang_code='a')"
