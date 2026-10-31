FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/captures /data/documents /app/var && chown -R appuser:appuser /data /app
COPY requirements-dev.lock requirements-inference.lock ./
ARG POSIFY_WITH_DETECTOR=false
RUN pip install --no-cache-dir -r requirements-dev.lock \
    && if [ "$POSIFY_WITH_DETECTOR" = "true" ]; then pip install --no-cache-dir -r requirements-inference.lock; fi
COPY pyproject.toml README.md ./
COPY services ./services
COPY scripts ./scripts
RUN pip install --no-deps .
USER appuser
CMD ["uvicorn", "posify.app:app", "--host", "0.0.0.0", "--port", "8000"]
