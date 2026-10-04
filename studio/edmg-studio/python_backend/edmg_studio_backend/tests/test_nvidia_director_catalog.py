from edmg_studio_backend.services.director_runtime_settings import DirectorRuntimeSettingsStore
from edmg_studio_backend.services.model_catalog import built_in_catalog
from edmg_studio_backend.services.model_manager import _hf_snapshot_download_profile


NEMOTRON_ID = "hf_nemotron3_nano_omni_30b_a3b_reasoning_bf16"
COSMOS_ID = "hf_cosmos_reason2_8b"


def test_nvidia_director_models_are_pinned_installable_catalog_entries():
    entries = {entry["id"]: entry for entry in built_in_catalog()}
    nemotron, cosmos = entries[NEMOTRON_ID], entries[COSMOS_ID]
    assert nemotron["recommended"] == "default"
    assert nemotron["hf_revision"] == "e5e9932441de940c9a62185c870ea5bcd4cd24e2"
    assert cosmos["hf_revision"] == "a9fae2cf89dc64db96b12860417f0eb403013bb9"
    assert nemotron["installable"] is True and cosmos["installable"] is True
    assert "configuration.py" in nemotron["required_files"]


def test_nemotron_snapshot_includes_pinned_remote_code():
    nemotron = next(entry for entry in built_in_catalog() if entry["id"] == NEMOTRON_ID)
    profile = _hf_snapshot_download_profile(nemotron, weight_format="metadata")
    assert "*.py" in profile.allow_patterns
    assert "*.jinja" in profile.allow_patterns


def test_director_settings_preserve_server_configuration_and_managed_catalog(tmp_path):
    store = DirectorRuntimeSettingsStore(tmp_path)
    settings = store.update({
        "primary_endpoint": "https://old.example/v1",
        "specialist_endpoint": "https://old.example/cosmos/v1",
        "primary_model": "remote-model",
        "specialist_model": "remote-specialist",
        "primary_execution": "server", "primary_server_model": "remote-model",
    })
    assert settings["primary_model"] == NEMOTRON_ID
    assert settings["specialist_model"] == COSMOS_ID
    assert settings["primary_endpoint"] == "https://old.example/v1"
    assert settings["specialist_endpoint"] == "https://old.example/cosmos/v1"
    restored = store.update({"primary_execution": "local"})
    assert restored["primary_endpoint"] == settings["primary_endpoint"]
    assert restored["primary_server_model"] == "remote-model"
