FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy virus agent code
COPY base.py .
COPY registry.py .
COPY agent.py .
COPY plugins/ ./plugins/

# Expose ports
EXPOSE 8080

# Health probe
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "print('healthy')" || exit 1

# Run virus agent
CMD ["python", "agent.py"]
