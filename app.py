import os
import time
from io import BytesIO
from flask import Flask, request, jsonify
from pydub import AudioSegment
import boto3
from botocore.exceptions import NoCredentialsError

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AWS_ACCESS_KEY = os.environ.get('AWS_ACCESS_KEY')
AWS_SECRET_KEY = os.environ.get('AWS_SECRET_KEY')
AWS_BUCKET_NAME = os.environ.get('AWS_BUCKET_NAME')
API_KEY        = os.environ.get('API_KEY')

if not all([AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_BUCKET_NAME, API_KEY]):
    raise Exception("Fehlende Umgebungsvariablen für AWS oder API-Key")

# Initialise S3 client
s3 = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def authenticate_request(req) -> bool:
    """Validate API-Key header."""
    return req.headers.get("API-Key") == API_KEY


def presigned_get_url(key: str, expires: int = 900) -> str:
    """Generate a time-limited download URL for an object."""
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": AWS_BUCKET_NAME, "Key": key},
        ExpiresIn=expires,
    )


def unique_filename(base: str, index: int) -> str:
    """Generate a collision-safe S3 object name."""
    ts = int(time.time() * 1e3)
    return f"{base}_{index}_{ts}.wav"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    return "Die Anwendung läuft!", 200


@app.route("/split-audio", methods=["POST"])
def split_audio():
    # ── Auth ────────────────────────────────────────────────────────────────
    if not authenticate_request(request):
        return jsonify({"error": "Unauthorized access"}), 401

    # ── File presence checks ────────────────────────────────────────────────
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    # ── Split audio into four equal parts ───────────────────────────────────
    audio           = AudioSegment.from_file(file)
    duration_ms     = len(audio)
    segment_length  = duration_ms // 4
    presigned_urls  = []

    for i in range(4):
        start = i * segment_length
        end   = duration_ms if i == 3 else (i + 1) * segment_length
        segment = audio[start:end]

        # Export segment to an in-memory buffer
        buffer = BytesIO()
        segment.export(buffer, format="wav")
        buffer.seek(0)

        object_key = unique_filename("segment", i + 1)

        try:
            # Upload without ACLs; bucket remains private
            s3.upload_fileobj(
                buffer,
                AWS_BUCKET_NAME,
                object_key,
                ExtraArgs={"ContentType": "audio/wav"},
            )

            # Generate a 15-minute presigned URL
            url = presigned_get_url(object_key, expires=900)
            presigned_urls.append(url)

        except NoCredentialsError:
            return jsonify({"error": "AWS credentials not available"}), 500

    # ── Response ───────────────────────────────────────────────────────────
    return jsonify(
        {
            "file_url_1": presigned_urls[0],
            "file_url_2": presigned_urls[1],
            "file_url_3": presigned_urls[2],
            "file_url_4": presigned_urls[3],
            "expires_in": 900,  # seconds
        }
    ), 200


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
