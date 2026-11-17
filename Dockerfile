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
RUN pip install --no-cache-dir ".[dashboard,webhooks]"

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 vectiq \
    && mkdir -p /config /data && chown vectiq /config /data
COPY --from=build /opt/venv /opt/venv
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
