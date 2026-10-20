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
# Copied only so the cleanliness check below can see them: both are baked into
# the runtime stage, so an uncommitted edit to either genuinely makes this image
# not match its commit.
COPY config ./config
COPY alembic.ini ./
# The image has no .git and no git, so the Info page's commit history has to be
# recorded *now*, while both are available. Copying .git is the price of being
# able to name the revision a running container came from. The generator writes
# the artifact and exits non-zero if it captured nothing, which fails the build:
# an image that cannot say what it is built from is worse than no image.
#
# --paths must list everything the image copies. Without it, `git status` would
# report every uncopied tracked file (tests/, docker-compose.yml, ...) as deleted
# and brand every single image a dirty build.
#
# .gitignore comes along with .git for the same reason: without it, anything the
# repository ignores but the build context still carries is reported as an
# untracked file. The .dockerignore now keeps those out as well, but the check
# should not depend on the two files staying in agreement.
COPY .git ./.git
COPY .gitignore ./.gitignore
# The line-ending attributes, because the check below runs `git status` *here* and
# git reads `.gitattributes` from the working tree. Without this file the builder has
# no `text=auto`, so a file committed as LF and checked out as CRLF compares as
# modified and *every* image is branded dirty -- the Info page then prints the right
# commit next to "has uncommitted changes", which is how a real warning becomes
# noise. See the note at the top of `.gitattributes`.
COPY .gitattributes ./.gitattributes
RUN PYTHONPATH=/build/src python -m awltux.buildinfo \
        --write /build/src/awltux/build_info.json \
        --paths src pyproject.toml README.md config alembic.ini

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install .

# The migrations must actually be present in the installed package, or a
# deployed container cannot migrate its own database. Fail the build rather than
# discovering it at runtime.
RUN test -f /opt/venv/lib/python3.12/site-packages/awltux/db/migrations/env.py \
 && test -d /opt/venv/lib/python3.12/site-packages/awltux/db/migrations/versions \
 && ls /opt/venv/lib/python3.12/site-packages/awltux/db/migrations/versions/*.py
# Same reasoning for the build provenance: if package-data failed to ship it -- or
# shipped one with no commits in it -- the Info page would silently fall back to
# "unavailable" in exactly the deployment that has no other way to answer. A file
# that exists but names nothing is not provenance, so the assertion is on content.
RUN test -s /opt/venv/lib/python3.12/site-packages/awltux/build_info.json \
 && python -c "import json; d = json.load(open('/opt/venv/lib/python3.12/site-packages/awltux/build_info.json')); assert d.get('commits'), 'build_info.json carries no commits'; assert d.get('head'), 'build_info.json names no revision'; print('provenance:', d['head'][:7], '-', len(d['commits']), 'commits')"


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
# The supervisor for the two processes (scheduler, web tier). See the file for why it is two.
COPY --chown=awltux:awltux docker/entrypoint.sh /app/entrypoint.sh
RUN chmod 0755 /app/entrypoint.sh

WORKDIR /app
USER awltux
VOLUME ["/data"]
EXPOSE 8080

# Shell form so ${AWLTUX_PORT} expands; the container's port is configurable.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${AWLTUX_PORT:-8080}/healthz" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
# One supervisor, two processes: the scheduler (exactly one) and the web tier (`--workers`).
# It migrates first, and stops the container if either process dies -- a web tier without a
# scheduler looks healthy and runs nothing.
CMD ["/bin/sh", "/app/entrypoint.sh"]
