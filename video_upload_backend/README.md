# Video Upload Backend (FastAPI)

This service provides a REST API endpoint to upload video files with a maximum size of 500MB. Successful uploads are stored on disk in the `./upload` directory by default (configurable via the `UPLOAD_DIR` environment variable).

## Features

- FastAPI backend with OpenAPI docs available at `/docs` and `/redoc`
- Upload endpoint: `POST /upload`
- Size limit: 500 MB
- Files are streamed and validated server-side to avoid reading the entire file into memory
- Files are saved under the configured upload directory with unique, timestamped names
- Robust error handling with standardized JSON error responses

## Running locally

1. Ensure Python 3.10+ is installed.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the server:

```bash
python -m src.api
```

The API will be available at: `http://localhost:8000`
- Docs: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Usage helper: `http://localhost:8000/docs/usage`

Note: The service will attempt to create the upload directory on startup (default `./upload`). Ensure the process has permission to write to this path. If you prefer a different path, set the `UPLOAD_DIR` environment variable or update `UPLOAD_DIR` in `src/api/main.py`.

## API

### Health check

- GET `/`
- Response: `{"message": "Healthy"}`

### Upload a video file

- POST `/upload`
- Content-Type: `multipart/form-data`
- Form field name: `file`
- Response: JSON object with details of the saved file.

Example `curl`:

```bash
curl -X POST http://localhost:8000/upload \
  -H 'Accept: application/json' \
  -F 'file=@/path/to/video.mp4'
```

### Errors

- 400: Missing file part or invalid request
- 413: Payload too large (exceeds 500MB)
- 415: Unsupported media type (if enabled)
- 500: Server-side errors (disk I/O, unexpected failures)

## Notes

- Files are saved using a unique name combining UTC timestamp and UUID, preserving the original extension.
- Partial/failed uploads are cleaned up.
- CORS is enabled for all origins; adjust in `src/api/main.py` for production.
