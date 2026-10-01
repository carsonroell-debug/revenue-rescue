FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
# scrapling[fetchers] needs Playwright's Chromium + OS deps for the
# DynamicFetcher/StealthyFetcher fallback tiers. On Fly.io builders the
# official Playwright CDN is reachable (no egress proxy).
RUN pip install --no-cache-dir -r requirements.txt \
 && python -m playwright install chromium \
 && python -m playwright install-deps chromium \
 && rm -rf /var/lib/apt/lists/*
COPY revenuerescue ./revenuerescue
EXPOSE 8787
CMD ["python", "-m", "revenuerescue.server"]
