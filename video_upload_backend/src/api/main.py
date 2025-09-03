import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Constants
MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB
# Use a writable relative directory instead of an absolute root path to avoid PermissionError
# The directory is relative to the working directory where the app is started.
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./upload")

# Application with metadata and tags for OpenAPI
app = FastAPI(
    title="Video Upload Backend",
    description=(
        "REST API for uploading video files. "
        "Enforces a 500MB size limit per file and stores accepted files in the upload directory."
    ),
    version="1.0.0",
    openapi_tags=[
        {
            "name": "health",
            "description": "Service health and metadata."
        },
        {
            "name": "uploads",
            "description": "Endpoints for uploading and validating video files."
        },
        {
            "name": "docs",
            "description": "Helpful documentation endpoints."
        }
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ErrorResponse(BaseModel):
    """Standardized error response."""
    detail: str = Field(..., description="A human-readable description of the error.")


class UploadResponse(BaseModel):
    """Response returned after a successful upload."""
    filename: str = Field(..., description="Original filename submitted by the client.")
    saved_as: str = Field(..., description="Saved filename on server.")
    size_bytes: int = Field(..., description="Size of the uploaded file in bytes.")
    content_type: Optional[str] = Field(None, description="Detected content type of the file.")
    upload_dir: str = Field(..., description="Directory path where file is saved.")


# PUBLIC_INTERFACE
@app.get("/", tags=["health"], summary="Health Check", description="Returns a simple health status for the service.")
def health_check():
    """Health check endpoint returning simple JSON status."""
    return {"message": "Healthy"}


# Ensure upload directory exists on startup
@app.on_event("startup")
def ensure_upload_dir() -> None:
    """Create the upload directory if it does not exist."""
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
    except Exception as exc:  # pragma: no cover
        # Using startup exception helps surface misconfigurations early
        raise RuntimeError(f"Failed to ensure upload directory at {UPLOAD_DIR}: {exc}") from exc


def _safe_destination_filename(original_name: str) -> str:
    """
    Create a safe unique filename preserving extension.
    E.g., input 'video.mp4' -> '20250101T120000Z_<uuid>.mp4'
    """
    base, ext = os.path.splitext(original_name)
    # Normalize extension to lowercase; keep even if empty
    ext = ext.lower()
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    unique = uuid.uuid4().hex
    return f"{ts}_{unique}{ext}"


async def _enforce_file_size(file: UploadFile) -> int:
    """
    Read the incoming file in chunks to enforce size limit and write to a temp file.
    Returns the total size if within limit. Raises HTTPException otherwise.

    We stream to disk to avoid loading entire file into memory.
    """
    chunk_size = 1024 * 1024  # 1MB
    total = 0
    tmp_path = os.path.join(UPLOAD_DIR, f".uploading_{uuid.uuid4().hex}.part")
    try:
        with open(tmp_path, "wb") as out:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_FILE_SIZE_BYTES:
                    # Stop early if exceeding limit
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File too large. Max allowed size is {MAX_FILE_SIZE_BYTES} bytes (500MB).",
                    )
                out.write(chunk)
    except HTTPException:
        # Cleanup partial file on size violation
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        finally:
            raise
    except Exception as exc:
        # Cleanup on any other read/write error
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        finally:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to receive file data: {exc}",
            )
    return total, tmp_path


# PUBLIC_INTERFACE
@app.post(
    "/upload",
    response_model=UploadResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        413: {"model": ErrorResponse, "description": "Payload Too Large"},
        415: {"model": ErrorResponse, "description": "Unsupported Media Type"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
    tags=["uploads"],
    summary="Upload a video file (max 500MB)",
    description=(
        "Accepts a single video file via multipart/form-data with the field name 'file'. "
        "The file is validated to be at most 500MB. On success, it is saved into the configured upload directory."
    ),
)
async def upload_video(file: UploadFile = File(..., description="The video file to upload.")) -> UploadResponse:
    """
    Upload a video file up to 500MB. The file must be provided as multipart/form-data with field name 'file'.

    Parameters:
    - file: UploadFile - The file uploaded by the client.

    Returns:
    - UploadResponse: Information about the saved file.

    Errors:
    - 400 if no file is provided.
    - 413 if the file exceeds 500MB.
    - 500 for server-side errors such as disk write failures.
    """
    if file is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file part provided.")

    # Optional content-type sanity check (not strictly enforced to avoid false negatives)
    # Accept common video mime types; otherwise still accept since browsers can be inconsistent.
    allowed_prefix = "video/"
    content_type = file.content_type or ""
    if not (content_type.startswith(allowed_prefix) or content_type in {"application/octet-stream", ""}):
        # Not strictly rejecting non-video to keep flexibility; if required uncomment below:
        # raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Only video files are allowed.")
        pass

    # Stream-read and enforce the size limit into a temporary file
    total_size, tmp_path = await _enforce_file_size(file)

    # Now finalize: move temp file to final destination with a safe unique name
    final_name = _safe_destination_filename(file.filename or "upload.bin")
    dest_path = os.path.join(UPLOAD_DIR, final_name)

    try:
        os.replace(tmp_path, dest_path)
    except Exception as exc:
        # Cleanup temp file if move fails
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        finally:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save file: {exc}",
            )

    return UploadResponse(
        filename=file.filename or final_name,
        saved_as=final_name,
        size_bytes=total_size,
        content_type=content_type if content_type else None,
        upload_dir=UPLOAD_DIR,
    )


# PUBLIC_INTERFACE
@app.get(
    "/docs/usage",
    tags=["docs"],
    summary="Upload API usage",
    description="Provides example curl command for uploading a file to the API.",
)
def docs_usage() -> dict:
    """
    Returns a simple usage example to assist clients with the upload endpoint.
    """
    return {
        "example_curl": (
            "curl -X POST http://localhost:8000/upload "
            "-H 'Accept: application/json' "
            "-F 'file=@/path/to/video.mp4'"
        ),
        "max_size_bytes": MAX_FILE_SIZE_BYTES,
        "upload_field": "file",
        "destination_dir": UPLOAD_DIR,
    }


# Global exception handlers to provide consistent JSON errors
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Return standardized JSON error for HTTPException."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return standardized JSON error for unhandled exceptions."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred."},
    )
