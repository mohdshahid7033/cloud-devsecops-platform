FROM python:3.14-alpine

ARG BUILD_REVISION="unknown"
ARG BUILD_DATE="unknown"

LABEL org.opencontainers.image.title="Cloud DevSecOps Platform" \
      org.opencontainers.image.description="Cloud-Based DevSecOps Platform with Blue/Green Deployments and Zero-Cost Telemetry" \
      org.opencontainers.image.source="https://github.com/mohdshahid7033/cloud-devsecops-platform" \
      org.opencontainers.image.revision="${BUILD_REVISION}" \
      org.opencontainers.image.created="${BUILD_DATE}"

RUN apk update && apk upgrade

WORKDIR /app

COPY app/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir "msgpack>=1.2.1" "setuptools>=78.1.1" && \
    pip uninstall -y pip setuptools wheel

COPY app/ .

EXPOSE 5000

CMD ["python", "app.py"]
