FROM ghcr.io/astral-sh/uv:0.11.16 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app /data /corpus \
    && chown -R app:app /app /data /corpus

WORKDIR /app
COPY --chown=app:app pyproject.toml uv.lock README.md ./
COPY --chown=app:app src ./src

USER app
RUN uv sync --frozen --no-dev --no-editable

ENV PATH="/app/.venv/bin:$PATH" \
    SPACE_STDS_DATA_DIR="/data" \
    SPACE_STDS_CORPUS_DIR="/corpus"

VOLUME ["/data"]
ENTRYPOINT ["space-stds"]
CMD ["serve"]

