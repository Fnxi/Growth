FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
COPY backend ./backend
RUN pip install --no-cache-dir .

CMD ["python", "-m", "app.monitor_scheduler"]
