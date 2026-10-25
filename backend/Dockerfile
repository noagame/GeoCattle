FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/pyproject.toml backend/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && useradd --create-home app && mkdir -p /data && chown app /data
COPY backend/geocattle geocattle
COPY database /database
RUN pip install --no-deps .
USER app
EXPOSE 8000
CMD ["uvicorn", "geocattle.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
USER root
COPY adapters/requirements.txt /tmp/adapter-requirements.txt
RUN pip install --no-cache-dir 'pytest>=8,<10' -r /tmp/adapter-requirements.txt
COPY backend/tests /app/tests
COPY adapters /app/adapters
COPY qa /app/qa
COPY scripts /app/scripts
USER app
CMD ["python", "-m", "pytest", "tests", "-q"]
