FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
 && python -m playwright install chromium \
 && python -m playwright install-deps chromium \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
 && mkdir -p /app/work /ms-playwright \
 && chown -R appuser:appuser /app \
 && chmod -R a+rX /ms-playwright

COPY --chown=appuser:appuser revenuerescue ./revenuerescue
COPY --chown=appuser:appuser scripts ./scripts
COPY --chown=appuser:appuser benchmarks ./benchmarks
COPY --chown=appuser:appuser docs ./docs
COPY --chown=appuser:appuser submission ./submission

USER appuser

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=3).read()" || exit 1

CMD ["python", "-m", "revenuerescue.server"]
