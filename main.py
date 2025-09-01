from flask import Flask, request, jsonify
from redis import Redis
import uuid
import threading
import time
import requests
from dotenv import load_dotenv
import os

load_dotenv()

# N8N_CALLBACK_URL = os.getenv("N8N_CALLBACK_URL", "http://n8n:5678/webhook-test/pipeline")
RAG_PIPELINE_SERVICE = os.getenv("RAG_PIPELINE_SERVICE", "http://localhost:5500/query")
REDIS_URL = os.getenv("REDIS_URL", "redis")
REDIS_PORT = os.getenv("REDIS_PORT", 6379)
REDIS_DB = os.getenv("REDIS_DB", 0)
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

app = Flask(__name__)
redis = Redis(host=REDIS_URL, port=REDIS_PORT, db=REDIS_DB, decode_responses=True, password=REDIS_PASSWORD)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

# --- API: Start workflow ---
@app.route("/workflow", methods=["POST"])
def start_workflow():
    data = request.get_json()
    task = data.get("task")

    job_id = str(uuid.uuid4())
    redis.set(job_id, '{"status":"processing","task":"%s"}' % task)
    print("Started Job: " + str(job_id) + " with task: " + str(task))

    # Push to queue
    redis.lpush("workflowQueue", f"{job_id}::{task}")

    return jsonify({"job_id": job_id, "status": "processing"})


# --- API: Get workflow status ---
@app.route("/workflow/<job_id>", methods=["GET"])
def get_workflow(job_id):
    job = redis.get(job_id)
    print("Job: " + str(job))
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(eval(job))  # stored as JSON-like string


# --- Worker that runs in background ---
def run_worker():
    print("Worker started")
    while True:
        job_data = redis.rpop("workflowQueue")
        if not job_data:
            time.sleep(1)
            continue

        job_id, task = job_data.split("::", 1)

        # --- Simulate long RAG pipeline ---
        print(f"Processing job {job_id}: {task}")

        try:
            print("Sending request to RAG pipeline service ", RAG_PIPELINE_SERVICE)
            # Send request to n8n
            response = requests.post(
                RAG_PIPELINE_SERVICE,
                json={"job_id": job_id, "task": task},
            )
            print("Response: " + str(response.json()))
            data = response.json()
            print("Received callback:" + str(data))
            if not data:
                return jsonify({"status": "error", "message": "No data provided"})

            job_id = data.get("job_id")
            status = data.get("status")
            result = data.get("result")

            redis.set(job_id, '{"status":"%s","result":"%s"}' % (status, result))
        except Exception as e:
            print("Error: " + str(e))


@app.route("/n8n/callback", methods=["POST"])
def n8n_callback():
    data = request.json
    print("Received callback:" + str(data))
    if not data:
        return jsonify({"status": "error", "message": "No data provided"})

    job_id = data.get("job_id")
    status = data.get("status")
    result = data.get("result")

    redis.set(job_id, '{"status":"%s","result":"%s"}' % (status, result))

    return jsonify({"status": "success"})


# Start worker in separate thread
worker_thread = threading.Thread(target=run_worker, daemon=True)
worker_thread.start()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
