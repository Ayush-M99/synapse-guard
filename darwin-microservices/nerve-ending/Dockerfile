FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    httpx==0.26.0 \
    nats-py==2.6.0

# Copy application
COPY nerve_ending.py .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Run the agent
CMD ["python", "nerve_ending.py"]
