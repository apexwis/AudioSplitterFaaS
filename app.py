import os
import time
from io import BytesIO

from flask import Flask, request, jsonify
from pydub import AudioSegment
import boto3
from botocore.client import Config
from botocore.exceptions import NoCredentialsError

app = Flask(__name__)

# ────────────────────────────  CONFIG  ──────────────────────────────────
AWS_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.environ.get("AWS_SECRET_KEY")
AWS_BUCKET_NAME = os.environ.get("AWS_BUCKET_NAME")
AWS_REGION     = os.environ.get("AWS_REGION")        # e.g. "eu-central-1"
API_KEY        = os.environ.get("API_KEY")

if not all([AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_BUCKET_NAME, API_KEY]):
    raise Exception("Fehlende Umgebungsvariablen für AWS oder API-Key")

# Force SigV4 signing
s3 = boto3.client(
    "s3",
    region_name=AWS_REGION,
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    config=Config(signature_version="s3v4"),
)

# ────────────────────────────  HELPERS  ─────────────────────────────────
def authenticate_request(req) -> bool:
    return req.headers.get("API-Key") == API_KEY


def presigned_get_url(key: str, expires: int = 900) -> str:
    """Return a time-limited (SigV4) download URL for an S3 object."""
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": AWS_BUCKET_NAME, "Key": key},
        ExpiresIn=expires,
    )


def unique_filename(base: str, index: int) -> str:
    """Generate a collision-safe S3 key."""
    ts = int(time.time() * 1e3)
    return f"{base}_{index}_{ts}.wav"

# ────────────────────────────  ROUTES  ──────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    return "Die Anwendung läuft!", 200


@app.route("/split-audio", methods=["POST"])
def split_audio():
    # ── auth ────────────────────────────────────────────────────────────
    if not authenticate_request(request):
        return jsonify({"error": "Unauthorized access"}), 401

    # ── file checks ─────────────────────────────────────────────────────
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    # ── split audio ─────────────────────────────────────────────────────
    audio           = AudioSegment.from_file(file)
    duration_ms     = len(audio)
    seg_len         = duration_ms // 4
    segments        = []                       # ← our new list of dicts

    for i in range(4):
        start = i * seg_len
        end   = duration_ms if i == 3 else (i + 1) * seg_len
        segment = audio[start:end]

        buf = BytesIO()
        segment.export(buf, format="wav")
        buf.seek(0)

        key = unique_filename("segment", i + 1)

        try:
            s3.upload_fileobj(
                buf,
                AWS_BUCKET_NAME,
                key,
                ExtraArgs={"ContentType": "audio/wav"},
            )

            segments.append({
                "url": presigned_get_url(key, expires=900),
                "key": key
            })

        except NoCredentialsError:
            return jsonify({"error": "AWS credentials not available"}), 500

    # ── response ────────────────────────────────────────────────────────
    return jsonify(
        {
            "segments": segments,   # [{url, key}, …]
            "expires_in": 900       # seconds
        }
    ), 200

# ────────────────────────────  MAIN  ────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
