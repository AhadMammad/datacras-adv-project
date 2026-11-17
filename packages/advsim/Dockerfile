# advsim image. Build context is the repository root (see docker-compose.yml):
# the simulator rebuilds advgen's model from source/ + overrides/ at start, and reads
# config/advsim, the manifest and the cross-system reference list.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 \
    ADV_ROOT=/app PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock ./
COPY packages/advgen/pyproject.toml packages/advgen/
COPY packages/advsim/pyproject.toml packages/advsim/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package advsim --no-install-workspace

COPY source source
COPY overrides overrides
COPY config config
COPY models/physical/manifest.json models/physical/
COPY mapping/cross_system_refs.csv mapping/
COPY packages/advgen packages/advgen
COPY packages/advsim packages/advsim
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package advsim

ENTRYPOINT ["advsim"]
CMD ["serve"]
