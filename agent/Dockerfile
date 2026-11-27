FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY devpilot_agent ./devpilot_agent
RUN pip install --no-cache-dir .
RUN useradd -m devpilot
USER devpilot
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "devpilot_agent.app:app", "--host", "0.0.0.0", "--port", "8000"]
