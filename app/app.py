from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/")
def home():
    return "Cloud-Based DevSecOps Platform is running!"


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "service": "devsecops-platform"
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
