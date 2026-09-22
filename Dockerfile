FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY guardian ./guardian

EXPOSE 8080
CMD ["python", "-m", "guardian.app"]
