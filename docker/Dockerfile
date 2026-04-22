# Dockerfile to build the matrixdotorg/sygnal docker images.
#
# To build the image, run `docker build` command from the root of the
# sygnal repository:
#
#    docker build -f docker/Dockerfile .
#

ARG DEBIAN_VERSION=trixie
ARG PYTHON_VERSION=3.12

###
### Stage 0: builder
###
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-${DEBIAN_VERSION}-slim AS builder

WORKDIR /app

# Don't download Python — use the one from the base image.
ENV UV_PYTHON_DOWNLOADS=never

# Silence a warning as uv can't do hardlinks between its cache
# (mounted as --mount=type=cache) and the target directory.
ENV UV_LINK_MODE=copy

# Compile bytecode for faster startup in production.
ENV UV_COMPILE_BYTECODE=true

# Install dependencies first (for Docker layer caching).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project --no-editable

# Copy the project source.
COPY pyproject.toml uv.lock README.md /app/
COPY sygnal /app/sygnal/

# Install the project itself.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

###
### Stage 1: runtime
###

FROM docker.io/library/python:${PYTHON_VERSION}-slim-${DEBIAN_VERSION}

# Copy the pre-built virtual environment from the builder.
COPY --from=builder /app/.venv /app/.venv

# Place the venv on the path so `sygnal` is directly available.
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 5000/tcp

ENTRYPOINT ["sygnal"]

HEALTHCHECK --start-period=25s --interval=15s --timeout=5s \
  CMD curl --fail --silent --show-error http://localhost:5000/health || exit 1
