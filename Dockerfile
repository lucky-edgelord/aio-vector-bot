# Vectiq in a container.  Build:  docker build -t vectiq .   Run: see docker-compose.yml
FROM python:3.12-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential cmake curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# vector-sdk-py has a Rust core and is built from source
RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
ENV PATH="/root/.cargo/bin:/opt/venv/bin:$PATH"
RUN python -m venv /opt/venv
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# The Sentire moderation bot, built into the image when SENTIRE=1
ARG SENTIRE=0
RUN if [ "$SENTIRE" = "1" ]; then \
      git clone --depth 1 https://github.com/VectorPrivacy/Sentire /sentire && \
      cd /sentire && cargo build --release --no-default-features && cp target/release/sentinel /usr/local/bin/sentinel; \
    else touch /usr/local/bin/sentinel.none; fi
# Optional modules: e.g. docker build --build-arg EXTRAS=dashboard,webhooks,music,nudenet .
ARG EXTRAS=dashboard,webhooks,music
RUN pip install --no-cache-dir ".[${EXTRAS}]"

FROM python:3.12-slim
# ffmpeg plays music in voice channels
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 vectiq \
    && mkdir -p /config /data && chown vectiq /config /data
COPY --from=build /opt/venv /opt/venv
COPY --from=build /usr/local/bin/sentinel* /usr/local/bin/
COPY config.yaml /opt/vectiq/config.example.yaml
COPY docker/entrypoint.sh /usr/local/bin/vectiq-entrypoint
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    VECTIQ_CONFIG=/config/config.yaml \
    VECTIQ_DATA_DIR=/data \
    VECTIQ_DASHBOARD_HOST=0.0.0.0
USER vectiq
WORKDIR /data
VOLUME ["/config", "/data"]
EXPOSE 8090 8080
ENTRYPOINT ["vectiq-entrypoint"]
CMD ["python", "-m", "vectiq"]
