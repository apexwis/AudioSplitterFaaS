import os
from flask import Flask, request, jsonify
from pydub import AudioSegment
from io import BytesIO
import boto3
from botocore.exceptions import NoCredentialsError

app = Flask(__name__)

# AWS-Zugangsdaten und API-Key aus den Umgebungsvariablen lesen
AWS_ACCESS_KEY = os.environ.get('AWS_ACCESS_KEY')
AWS_SECRET_KEY = os.environ.get('AWS_SECRET_KEY')
AWS_BUCKET_NAME = os.environ.get('AWS_BUCKET_NAME')
API_KEY = os.environ.get('API_KEY')

# Überprüfe, ob die Zugangsdaten vorhanden sind
if not AWS_ACCESS_KEY or not AWS_SECRET_KEY or not AWS_BUCKET_NAME or not API_KEY:
    raise Exception("Fehlende Umgebungsvariablen für AWS oder API-Key")

# Initialisiere den S3-Client
s3 = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY
)

def authenticate_request(request):
    """Prüft, ob der API-Key in der Anfrage korrekt ist."""
    client_api_key = request.headers.get('API-Key')
    return client_api_key == API_KEY

@app.route('/', methods=['GET'])
def index():
    return 'Die Anwendung läuft!', 200

@app.route('/split-audio', methods=['POST'])
def split_audio():
    if not authenticate_request(request):
        return jsonify({"error": "Unauthorized access"}), 401

    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    audio = AudioSegment.from_file(file)
    duration = len(audio)
    segment_length = duration // 4

    file_urls = []

    for i in range(4):
        start_time = i * segment_length
        end_time = (i + 1) * segment_length if i < 3 else duration
        segment = audio[start_time:end_time]

        segment_io = BytesIO()
        segment.export(segment_io, format="wav")
        segment_io.seek(0)

        file_name = f'segment_{i + 1}.wav'

        try:
            s3.upload_fileobj(
                segment_io,
                AWS_BUCKET_NAME,
                file_name,
                ExtraArgs={
                    'ContentType': 'audio/wav'
                }
            )

            file_url = f'https://{AWS_BUCKET_NAME}.s3.amazonaws.com/{file_name}'
            file_urls.append(file_url)

        except NoCredentialsError:
            return jsonify({'error': 'AWS credentials not available'}), 500

    return jsonify({
        "file_url_1": file_urls[0],
        "file_url_2": file_urls[1],
        "file_url_3": file_urls[2],
        "file_url_4": file_urls[3]
    }), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
