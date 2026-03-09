FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml .
COPY src ./src
RUN pip install --no-cache-dir .

CMD ["python", "-m", "second_brain_service.cli", "serve-http"]
