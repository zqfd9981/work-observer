FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.26
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY migrations ./migrations
RUN uv sync --locked --no-dev
RUN useradd --create-home --uid 10001 observer && mkdir -p data reports && chown -R observer:observer /app
USER observer
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1
EXPOSE 8765
CMD ["uv", "run", "--locked", "--no-dev", "work-observer", "serve", "--host", "0.0.0.0"]
