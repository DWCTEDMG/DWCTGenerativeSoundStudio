from __future__ import annotations

import os
import tempfile

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings
from .provider_factory import build_provider
from .schemas import PlanRequest, PlanResponse, HealthResponse


settings = Settings()
provider = build_provider(settings)

app = FastAPI(title="EDMG AI Service", version="0.1.0")

# Helpful when calling from Electron/Gradio
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(ok=True, provider=provider.name, model=getattr(provider, "model", None))


async def _persist_upload_to_tempfile(file: UploadFile, *, suffix: str, chunk_size: int = 1024 * 1024) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            tmp.write(chunk)
        tmp_path = tmp.name
    try:
        await file.close()
    except Exception:
        pass
    return tmp_path


@app.post("/v1/plan", response_model=PlanResponse)
def plan(req: PlanRequest) -> PlanResponse:
    return provider.plan(req)


def _coerce_bool(value: object, default: bool = True) -> bool:
    raw = str(value if value is not None else "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


@app.post("/v1/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    model_size: str = "turbo",
    provider: str = "faster_whisper",
    device: str = "cpu",
    compute_type: str = "int8",
    fallback_to_whisper: str = "1",
) -> dict:
    try:
        from .asr import transcribe_detailed
    except Exception as e:
        raise HTTPException(status_code=501, detail=str(e))

    suffix = "." + (file.filename.split(".")[-1] if file.filename and "." in file.filename else "wav")
    tmp_path = await _persist_upload_to_tempfile(file, suffix=suffix)

    try:
        return transcribe_detailed(
            tmp_path,
            model_size=model_size,
            provider=provider,
            device=device,
            compute_type=compute_type,
            fallback_to_whisper=_coerce_bool(fallback_to_whisper, True),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@app.post("/v1/audio_features")
async def audio_features(file: UploadFile = File(...)) -> dict:
    try:
        from .audio import lightweight_audio_features
    except Exception as e:
        raise HTTPException(status_code=501, detail=str(e))

    suffix = "." + (file.filename.split(".")[-1] if file.filename and "." in file.filename else "wav")
    tmp_path = await _persist_upload_to_tempfile(file, suffix=suffix)

    try:
        feats = lightweight_audio_features(tmp_path)
        return feats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
