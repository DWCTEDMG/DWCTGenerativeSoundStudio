import pytest
from fastapi.testclient import TestClient
from enhanced_deforum_music_generator.api.main import app
from enhanced_deforum_music_generator.api import analysis as analysis_api
from unittest.mock import patch

client = TestClient(app)

def test_health():
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_status():
    response = client.get("/status/")
    assert response.status_code == 200
    assert "service" in response.json()


def test_analyze_audio_accepts_large_upload():
    payload = (b"tone" * 4096) + b"tail"

    def fake_analyze(self, audio_path, enable_cache=True):
        with open(audio_path, "rb") as handle:
            assert handle.read() == payload
        return {
            "tempo": 120.0,
            "duration": 601.0,
            "sample_rate": 22050,
            "beats": [0.5, 1.0],
            "energy": [0.1, 0.2],
            "onset_strength": [0.3],
            "onset_times": [0.25],
            "spectral_centroid": [123.0],
            "spectral_rolloff": [456.0],
            "rms_energy": [0.4],
        }

    with patch.object(analysis_api.AudioAnalyzer, "analyze", fake_analyze):
        response = client.post(
            "/analysis/analyze-audio?max_duration=1800",
            files={"file": ("long.wav", payload, "audio/wav")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["duration"] == pytest.approx(601.0)
    assert body["sample_rate"] == 22050
    assert body["tempo_bpm"] == pytest.approx(120.0)
