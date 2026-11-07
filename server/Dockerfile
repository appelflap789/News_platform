# The platform on the home server (README, "On the home server"). Built there by server/deploy.sh, which
# copies the code next to it; the library, the model and the keys are mounted in, never built in.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    NSP_HOST=0.0.0.0 \
    NSP_PORT=8765 \
    NSP_DATA_DIR=/data \
    NSP_MODELS_DIR=/data/models \
    NSP_ENV_FILE=/config/.env

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

COPY backend backend
COPY frontend/dist frontend/dist
COPY tests tests
COPY run.py pytest.ini ./

EXPOSE 8765
CMD ["python", "run.py", "--no-browser"]
