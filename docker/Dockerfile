FROM python:3.14-alpine
RUN apk update && apk upgrade

WORKDIR /app

COPY app/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir "msgpack>=1.2.1" "setuptools>=78.1.1"

COPY app/ .

EXPOSE 5000

CMD ["python", "app.py"]
