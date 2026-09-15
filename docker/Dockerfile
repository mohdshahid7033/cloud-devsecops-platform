FROM python:3.14-slim
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY app/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir "msgpack>=1.2.1" "setuptools>=78.1.1"

COPY app/ .

EXPOSE 5000

CMD ["python", "app.py"]
