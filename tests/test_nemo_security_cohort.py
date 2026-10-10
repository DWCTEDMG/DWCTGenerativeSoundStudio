"""Security and compatibility checks for NeMo's narrow dependency overrides.

Run with the locked parakeet capability and accelerator profile in an isolated
environment. The CUDA model roundtrip is opt-in; it uses random weights and
does not claim pretrained Parakeet transcription quality.
"""
import os

import pytest


def test_hydra_instantiate_cannot_rename_files(tmp_path):
    hydra = pytest.importorskip("hydra")
    from hydra.errors import InstantiationException

    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_text("unchanged", encoding="utf-8")
    with pytest.raises(InstantiationException):
        hydra.utils.instantiate({"_target_": "os.rename", "src": str(source), "dst": str(destination)})
    assert source.read_text(encoding="utf-8") == "unchanged"
    assert not destination.exists()


def test_hydra_logging_factory_cannot_rename_files(tmp_path):
    pytest.importorskip("hydra")
    from hydra.core.utils import configure_log
    from omegaconf import OmegaConf

    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_text("unchanged", encoding="utf-8")
    config = OmegaConf.create({"version": 1, "handlers": {"escape": {
        "()": "os.rename", "src": str(source), "dst": str(destination),
    }}, "root": {"handlers": ["escape"], "level": "INFO"}})
    with pytest.raises(ValueError):
        configure_log(config)
    assert source.read_text(encoding="utf-8") == "unchanged"
    assert not destination.exists()


def test_fsspec_reference_templates_refuse_python_attribute_escape():
    fsspec = pytest.importorskip("fsspec")
    from jinja2.exceptions import SecurityError

    reference = {"version": 1, "refs": {}, "gen": [{
        "key": "{{ [].__class__.__mro__ }}", "url": "memory://{{ i }}",
        "dimensions": {"i": [0]},
    }]}
    with pytest.raises(SecurityError):
        fsspec.filesystem("reference", fo=reference, simple_templates=False)
    safe = fsspec.filesystem("reference", fo={"version": 1, "refs": {"hello": "world"}})
    assert safe.cat("hello") == b"world"


def test_datasets_local_save_restore_with_patched_fsspec(tmp_path):
    datasets = pytest.importorskip("datasets")
    import pyarrow as pa

    path = tmp_path / "dataset"
    # Isolate filesystem compatibility from Arrow/dill's automatic fingerprint
    # serialization, which has a separate MonthDayNano pickling issue.
    original = datasets.Dataset(pa.table({"text": ["Studio audio", "security check"]}),
                                fingerprint="edmg-security-filesystem-smoke")
    original.save_to_disk(str(path))
    restored = datasets.load_from_disk(str(path))
    assert restored["text"] == original["text"]


@pytest.mark.skipif(os.environ.get("EDMG_TEST_NEMO_SECURITY_COHORT") != "1",
                    reason="requires isolated locked NeMo CUDA capability")
def test_nemo_cuda_model_forward_and_save_restore(tmp_path):
    import torch
    from nemo.collections.asr.models import EncDecCTCModel
    from omegaconf import OmegaConf

    assert torch.cuda.is_available()
    config = OmegaConf.create({
        "sample_rate": 16000, "labels": ["a", "b"],
        "preprocessor": {"_target_": "nemo.collections.asr.modules.AudioToMelSpectrogramPreprocessor",
                         "sample_rate": 16000, "features": 16, "n_fft": 512},
        "encoder": {"_target_": "nemo.collections.asr.modules.ConvASREncoder",
                    "feat_in": 16, "activation": "relu", "conv_mask": True,
                    "jasper": [{"filters": 16, "repeat": 1, "kernel": [11], "stride": [1],
                                "dilation": [1], "dropout": 0.0, "residual": False, "separable": True}]},
        "decoder": {"_target_": "nemo.collections.asr.modules.ConvASRDecoder",
                    "feat_in": 16, "num_classes": 2, "vocabulary": ["a", "b"]},
    })
    model = EncDecCTCModel(cfg=config).cuda().eval()
    with torch.inference_mode():
        result = model(input_signal=torch.randn(1, 16000, device="cuda"),
                       input_signal_length=torch.tensor([16000], device="cuda"))
    assert result[0].shape[0] == 1
    path = tmp_path / "model.nemo"
    model.save_to(str(path))
    restored = EncDecCTCModel.restore_from(str(path), map_location="cuda").eval()
    assert all(torch.equal(a, b) for a, b in zip(model.parameters(), restored.parameters()))
