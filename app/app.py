from flask import Flask, jsonify
from prometheus_flask_exporter import PrometheusMetrics

app = Flask(__name__)
metrics = PrometheusMetrics(app)

@app.route("/", methods=["GET"])
def home():
    return "Cloud-Based DevSecOps Platform is running!"


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "service": "devsecops-platform"
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
