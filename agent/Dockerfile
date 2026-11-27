FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY devpilot_agent ./devpilot_agent
RUN pip install --no-cache-dir .
RUN useradd -m devpilot
USER devpilot
EXPOSE 8000
HEALTHCHECK CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/health', timeout=3)"
CMD ["sh", "-c", "exec uvicorn devpilot_agent.app:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
