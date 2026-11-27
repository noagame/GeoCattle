FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/pyproject.toml backend/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && useradd --create-home app && mkdir -p /data && chown app /data
COPY backend/geocattle geocattle
COPY adapters /app/adapters
COPY database /database
RUN pip install --no-cache-dir --no-deps -e .
USER app
EXPOSE 8000
CMD ["uvicorn", "geocattle.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
USER root
COPY adapters/requirements.txt /tmp/adapter-requirements.txt
RUN pip install --no-cache-dir 'pytest>=8,<10' 'openpyxl>=3.1,<4' -r /tmp/adapter-requirements.txt
COPY backend/tests /app/tests
COPY qa /app/qa
COPY scripts /app/scripts
USER app
CMD ["python", "-m", "pytest", "tests", "-q"]
