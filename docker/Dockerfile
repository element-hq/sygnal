# Dockerfile to build the matrixdotorg/sygnal docker images.
#
# To build the image, run `docker build` command from the root of the
# sygnal repository:
#
#    docker build -f docker/Dockerfile .
#

ARG DEBIAN_VERSION=bookworm
ARG PYTHON_VERSION=3.12

###
### Stage 0: builder
###
### This stage is platform-agnostic, so we can use the build platform in case of cross-compilation.
###
FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-${DEBIAN_VERSION} AS builder

WORKDIR /sygnal

# This silences a warning as uv isn't able to do hardlinks between its cache
# (mounted as --mount=type=cache) and the target directory.
ENV UV_LINK_MODE=copy

# Copy what we need for dependency resolution
COPY pyproject.toml uv.lock README.md /sygnal/

# If specified, we won't verify the hashes of dependencies.
# This is only needed if the hashes of dependencies cannot be checked for some
# reason, such as when a git repository is used directly as a dependency.
ARG TEST_ONLY_SKIP_DEP_HASH_VERIFICATION

# If specified, we won't use the lockfile.
# Instead, we'll just install what a regular `pip install` would from PyPI.
ARG TEST_ONLY_IGNORE_LOCKFILE

# Install dependencies first (for Docker layer caching)
RUN --mount=type=cache,target=/root/.cache/uv \
  if [ -z "$TEST_ONLY_IGNORE_LOCKFILE" ]; then \
    uv export --no-dev --frozen -o /sygnal/requirements.txt; \
  else \
    touch /sygnal/requirements.txt; \
  fi

RUN --mount=type=cache,target=/root/.cache/uv \
  uv pip install --prefix="/install" --no-deps -r /sygnal/requirements.txt

# Copy over the rest of the sygnal source code.
COPY sygnal /sygnal/sygnal/

# Install the sygnal package itself.
RUN \
  --mount=type=cache,target=/root/.cache/uv \
  --mount=type=cache,target=/sygnal/target,sharing=locked \
  --mount=type=cache,target=${CARGO_HOME}/registry,sharing=locked \
  if [ -z "$TEST_ONLY_IGNORE_LOCKFILE" ]; then \
    uv pip install --prefix="/install" --no-deps /sygnal; \
  else \
    uv pip install --prefix="/install" /sygnal; \
  fi

###
### Stage 1: runtime
###

FROM docker.io/library/python:${PYTHON_VERSION}-slim-${DEBIAN_VERSION}

COPY --from=builder /install /usr/local

EXPOSE 5000/tcp

ENTRYPOINT ["python", "-m", "sygnal.sygnal"]

HEALTHCHECK --start-period=25s --interval=15s --timeout=5s \
  CMD curl --fail --silent --show-error http://localhost:5000/health || exit 1
