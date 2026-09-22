import hashlib
import os
import socket
import time

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

INSTANCE_NAME = socket.gethostname()


@app.route("/")
def index():
    return render_template(
        "index.html",
        instance_name=INSTANCE_NAME
    )


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "instance": INSTANCE_NAME
    }), 200


@app.route("/work")
def work():
    """
    Endpoint used by the experiment to generate controlled CPU load.
    The amount of work is intentionally bounded.
    """
    try:
        intensity = int(request.args.get("intensity", 50000))
    except ValueError:
        return jsonify({"error": "intensity must be an integer"}), 400

    # Prevent accidental excessive workloads.
    intensity = max(1000, min(intensity, 500000))

    start = time.perf_counter()

    value = b"aws-custom-autoscaling-controller"

    for _ in range(intensity):
        value = hashlib.sha256(value).digest()

    elapsed = time.perf_counter() - start

    return jsonify({
        "status": "completed",
        "instance": INSTANCE_NAME,
        "intensity": intensity,
        "processing_time_seconds": round(elapsed, 4)
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
