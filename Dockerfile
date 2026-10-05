# AwltuxTrading container image.
#
# Multi-stage: dependencies are built in a throwaway layer so the runtime image
# carries no compilers, and the process runs as a non-root user with the data
# volume as the only writable path.
#
# The package is installed **non-editable** into the venv in the builder stage,
# and the runtime stage copies only the venv plus the two things that live outside
# the package: `config/config.yaml` and `alembic.ini`. An earlier version also
# copied `src/` and tried an editable install, which silently failed (no
# `pyproject.toml` present at that point) and left two copies of the code in the
# image -- one of them stale.

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# lxml needs these to build if no wheel matches the platform. git is only here to
# read the commit history that gets baked into the package (see below); neither
# the wheel nor the runtime stage needs it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libxml2-dev libxslt1-dev git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
# The image has no .git and no git, so the Info page's commit history has to be
# recorded *now*, while both are available. Copying .git is the price of being
# able to name the revision a running container came from. The generator writes
# the artifact and exits non-zero if it captured nothing, which fails the build:
# an image that cannot say what it is built from is worse than no image.
COPY .git ./.git
RUN PYTHONPATH=/build/src python -m awltux.buildinfo --write /build/src/awltux/build_info.json

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install .

# The migrations must actually be present in the installed package, or a
# deployed container cannot migrate its own database. Fail the build rather than
# discovering it at runtime.
RUN test -f /opt/venv/lib/python3.12/site-packages/awltux/db/migrations/env.py \
 && test -d /opt/venv/lib/python3.12/site-packages/awltux/db/migrations/versions \
 && ls /opt/venv/lib/python3.12/site-packages/awltux/db/migrations/versions/*.py
# Same reasoning for the build provenance: if package-data failed to ship it, the
# Info page would silently fall back to "unavailable" in exactly the deployment
# that has no other way to answer.
RUN test -s /opt/venv/lib/python3.12/site-packages/awltux/build_info.json


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    AWLTUX_DATA_DIR=/data \
    AWLTUX_CONFIG_FILE=/app/config/config.yaml \
    AWLTUX_ALEMBIC_INI=/app/alembic.ini \
    AWLTUX_HOST=0.0.0.0 \
    AWLTUX_PORT=8080

# curl is only for the container healthcheck; tini reaps the scheduler's threads
# cleanly on SIGTERM so a restart cannot leave a half-written SQLite WAL behind.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl tini libxml2 libxslt1.1 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 awltux \
 && mkdir -p /data /app \
 && chown -R awltux:awltux /data /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=awltux:awltux config /app/config
# alembic.ini is needed at *runtime*: the container migrates on start so a restart
# against an existing volume picks up schema changes instead of failing on a
# renamed or newly added column.
COPY --chown=awltux:awltux alembic.ini /app/alembic.ini

WORKDIR /app
USER awltux
VOLUME ["/data"]
EXPOSE 8080

# Shell form so ${AWLTUX_PORT} expands; the container's port is configurable.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${AWLTUX_PORT:-8080}/healthz" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
# Migrate, then serve. The `&&` is deliberate: serving on a schema the code does
# not expect produces 500s that look like application bugs, which is exactly how
# the missing migration went unnoticed until the dashboard failed.
CMD ["sh", "-c", "python -m awltux.cli migrate && python -m awltux.cli serve"]
