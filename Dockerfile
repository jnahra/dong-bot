FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY dongbot ./dongbot
ENV STATE_FILE=/data/state.json OUT_DIR=/data/out PYTHONUNBUFFERED=1
VOLUME /data
CMD ["python", "-m", "dongbot", "run"]
