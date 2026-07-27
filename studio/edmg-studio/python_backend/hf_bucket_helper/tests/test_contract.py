from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from edmg_hf_bucket_helper.__main__ import ContractError, execute


@dataclass
class FakeEntry:
    type: str
    path: str
    size: int = 0


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def bucket_info(self, bucket, *, token=None):
        self.calls.append(("info", bucket, token))
        return {"id": bucket, "private": False}

    def list_bucket_tree(self, bucket, prefix=None, *, recursive=False, token=None):
        self.calls.append(("list", bucket, prefix, recursive, token))
        return [FakeEntry(type="file", path="weights/model.safetensors", size=7)]

    def get_bucket_paths_info(self, bucket, paths, *, token=None):
        self.calls.append(("paths_info", bucket, list(paths), token))
        return [FakeEntry(type="file", path=paths[0], size=7)]

    def download_bucket_files(self, bucket, files, *, raise_on_missing_files=False, token=None):
        self.calls.append(("download", bucket, files, raise_on_missing_files, token))
        Path(files[0][1]).write_bytes(b"weights")

    def batch_bucket_files(self, bucket, *, add=None, token=None):
        self.calls.append(("upload", bucket, add, token))

    def sync_bucket(self, source=None, dest=None, **kwargs):
        self.calls.append(("sync", source, dest, kwargs))


def request(operation: str, **kwargs):
    return {"contract_version": 1, "operation": operation, "bucket": "team/models", **kwargs}


def test_token_only_travels_through_environment(tmp_path) -> None:
    api = FakeApi()
    result = execute(
        request("list", prefix="weights", recursive=True),
        api=api,
        environment={"HF_TOKEN": "secret-token"},
    )
    assert result["entries"][0]["path"] == "weights/model.safetensors"
    assert api.calls == [("list", "team/models", "weights", True, "secret-token")]
    with pytest.raises(ContractError, match="never in the request"):
        execute({**request("bucket_info"), "token": "not-allowed"}, api=api)


def test_public_bucket_uses_explicit_anonymous_auth() -> None:
    api = FakeApi()
    result = execute(request("bucket_info"), api=api, environment={})

    assert result["bucket"]["id"] == "team/models"
    assert api.calls == [("info", "team/models", False)]


def test_file_download_and_upload_contract(tmp_path) -> None:
    api = FakeApi()
    destination = tmp_path / "nested" / "model.bin"
    result = execute(
        request("download", remote_path="weights/model.bin", local_path=str(destination)),
        api=api,
        environment={},
    )
    assert result["exists"] is True
    assert destination.read_bytes() == b"weights"

    execute(
        request("upload", remote_path="weights/model.bin", local_path=str(destination)),
        api=api,
        environment={},
    )
    assert [call[0] for call in api.calls] == ["download", "upload"]


def test_sync_requires_one_local_and_one_bucket_path() -> None:
    api = FakeApi()
    execute(
        request(
            "sync",
            source="C:/models",
            dest="hf://buckets/team/models/weights",
            include=["model_index.json", "unet/diffusion_pytorch_model.safetensors"],
            exclude=["**/.cache/**", "**/*.incomplete"],
        ),
        api=api,
        environment={},
    )
    assert api.calls[0][0] == "sync"
    assert api.calls[0][3]["include"] == [
        "model_index.json",
        "unet/diffusion_pytorch_model.safetensors",
    ]
    assert api.calls[0][3]["exclude"] == ["**/.cache/**", "**/*.incomplete"]
    with pytest.raises(ContractError, match="exactly one local path"):
        execute(
            request(
                "sync",
                source="hf://buckets/team/models/a",
                dest="hf://buckets/team/models/b",
            ),
            api=api,
            environment={},
        )


def test_sync_rejects_invalid_include_patterns() -> None:
    with pytest.raises(ContractError, match="include must be"):
        execute(
            request(
                "sync",
                source="C:/models",
                dest="hf://buckets/team/models/weights",
                include=["model_index.json", ""],
            ),
            api=FakeApi(),
            environment={},
        )
