FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=7860 APP_DATA_DIR=/data
WORKDIR /app
RUN useradd -m -u 1000 appuser && mkdir -p /data && chown appuser:appuser /data
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.11.0 \
    && pip install --no-cache-dir -r requirements.txt
COPY --chown=appuser:appuser server ./server
COPY --chown=appuser:appuser model_v1 ./model_v1
COPY --chown=appuser:appuser model_v3 ./model_v3
USER appuser
EXPOSE 7860
CMD ["python", "server/public_server.py"]
