# Public Pulse dashboards on Railway. Built from the bundle that deploy/stage_public.py writes,
# never from the repo root (the root holds .env, personal reports and the full database).
FROM python:3.12-slim

# Public mode is baked into the image, so forgetting the Railway variable can't expose the
# personal pages.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PULSE_PUBLIC_MODE=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x start.sh

CMD ["./start.sh"]
