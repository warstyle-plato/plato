# syntax=docker/dockerfile:1
# Dedicated dispatcher image: no PLATO application, client files, or host auth.
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY scripts/plato_dispatcher/requirements.txt /app/requirements.txt
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then \
      pip install --cert /run/secrets/proxy_ca --no-cache-dir -r /app/requirements.txt; \
    else \
      pip install --no-cache-dir -r /app/requirements.txt; \
    fi
COPY scripts/plato_dispatcher/ /app/scripts/plato_dispatcher/
COPY scripts/plato_dispatcher_deploy/start.sh /app/start-dispatcher.sh
RUN chmod 755 /app/start-dispatcher.sh \
    && mkdir -p /root/.codex /root/.ssh /workspace \
    && chmod 700 /root/.codex /root/.ssh \
    && usermod --unlock root \
    && git -C /workspace init -q

# The default Codex home is mounted by the proposed Blueprint. No credentials
# are baked into the image and no HOME/CODEX_HOME overrides are required.
CMD ["/app/start-dispatcher.sh"]
