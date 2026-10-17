FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev --no-install-project
COPY contracts ./contracts
COPY backend ./backend
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["sh", "-c", "python -m contracts.migrations.apply && uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"]
