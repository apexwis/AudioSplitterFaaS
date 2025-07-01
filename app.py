import os
import time
import subprocess
import tempfile
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


def unique_filename(base: str, index: int, ext: str = "mp3") -> str:
    """Generate a collision-safe S3 key with the requested extension."""
    ts = int(time.time() * 1e3)
    return f"{base}_{index}_{ts}.{ext}"

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

    upload = request.files["file"]
    if upload.filename == "":
        return jsonify({"error": "No file selected"}), 400

    # ── persist original upload to temp file for ffmpeg ────────────────
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_in:
        upload.save(tmp_in)
        input_path = tmp_in.name

    # ── determine duration (ms) for equal chunks ───────────────────────
    audio        = AudioSegment.from_file(input_path)
    duration_ms  = len(audio)
    seg_len_ms   = duration_ms // 4
    segments     = []

    # ── split via ffmpeg -c:a copy (no re-encode) ───────────────────────
    for i in range(4):
        start_ms      = i * seg_len_ms
        end_ms        = duration_ms if i == 3 else (i + 1) * seg_len_ms
        start_sec     = start_ms / 1000
        duration_sec  = (end_ms - start_ms) / 1000

        ffmpeg_cmd = [
            "ffmpeg",
            "-hide_banner", "-loglevel", "error",
            "-ss", str(start_sec),
            "-t", str(duration_sec),
            "-i", input_path,
            "-c:a", "copy",               # ★ lossless slice
            "-f", "mp3",
            "pipe:1"
        ]

        try:
            proc = subprocess.run(
                ffmpeg_cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
        except subprocess.CalledProcessError as e:
            return jsonify({"error": "ffmpeg failed", "details": e.stderr.decode()}), 500

        buf = BytesIO(proc.stdout)
        buf.seek(0)

        key = unique_filename("segment", i + 1, ext="mp3")

        try:
            s3.upload_fileobj(
                buf,
                AWS_BUCKET_NAME,
                key,
                ExtraArgs={"ContentType": "audio/mpeg"},
            )
            segments.append({
                "url": presigned_get_url(key, expires=900),
                "key": key
            })
        except NoCredentialsError:
            return jsonify({"error": "AWS credentials not available"}), 500

    # ── clean-up temp file ──────────────────────────────────────────────
    try:
        os.remove(input_path)
    except OSError:
        pass

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
