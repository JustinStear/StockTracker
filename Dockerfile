FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY config.example.yaml /app/config.example.yaml

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . && \
    playwright install chromium

EXPOSE 8000

CMD ["stockcheck", "web", "--host", "0.0.0.0", "--port", "8000"]
