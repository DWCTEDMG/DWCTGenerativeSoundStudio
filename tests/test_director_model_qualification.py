"""Reject missing/truncated/escaping weights without loading model code or CUDA."""
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("director_qualification", Path(__file__).parents[1] / "scripts/qualify_director_models.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InstalledModelAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "config.json").write_text('{"model_type":"qwen3_vl"}')
        (self.root / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"weight": "shard.safetensors"}}))
        header = json.dumps({"weight": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}).encode()
        (self.root / "shard.safetensors").write_bytes(struct.pack("<Q", len(header)) + header + b"\0" * 4)
        metadata = self.root / ".cache/huggingface/download"
        metadata.mkdir(parents=True)
        (metadata / "config.json.metadata").write_text("a" * 40 + "\netag\n0\n")

    def test_complete_structure_is_not_payload_integrity_or_production_proof(self):
        receipt = module.audit(self.root)
        self.assertEqual(receipt["state"], "installed_structure_valid")
        self.assertIn("payload hashes not verified", receipt["integrity_scope"])

    def test_truncated_tensor_is_rejected(self):
        shard = self.root / "shard.safetensors"
        shard.write_bytes(shard.read_bytes()[:-1])
        self.assertIn("truncated tensor", module.audit(self.root)["errors"][0])

    def test_missing_shard_is_rejected(self):
        (self.root / "shard.safetensors").unlink()
        self.assertIn("missing shard", module.audit(self.root)["errors"][0])

    def test_missing_model_metadata_returns_failure_evidence(self):
        (self.root / "config.json").unlink()
        self.assertEqual(module.audit(self.root)["state"], "incomplete")

    def test_shard_cannot_escape_installed_directory(self):
        (self.root / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"weight": "../outside.safetensors"}}))
        self.assertIn("unauthorized shard", module.audit(self.root)["errors"][0])

    def test_mixed_revisions_are_rejected(self):
        (self.root / ".cache/huggingface/download/tokenizer.json.metadata").write_text("b" * 40 + "\netag\n0\n")
        self.assertEqual(module.audit(self.root)["state"], "incomplete")


if __name__ == "__main__":
    unittest.main()
