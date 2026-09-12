FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra extract
COPY tmod ./tmod
COPY web ./web
COPY db ./db
COPY scripts ./scripts
COPY data/zip_centroids.csv ./data/zip_centroids.csv
RUN uv sync --frozen --no-dev --extra extract
EXPOSE 8090
CMD ["uv", "run", "--no-sync", "uvicorn", "tmod.web.app:app", "--host", "0.0.0.0", "--port", "8090"]
