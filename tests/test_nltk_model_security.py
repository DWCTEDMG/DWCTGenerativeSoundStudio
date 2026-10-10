"""Exercise the unreleased NLTK model-artifact fix, not just its version string."""
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

nltk = pytest.importorskip("nltk")
from nltk import pathsec
from nltk.classify.maxent import save_maxent_params
from nltk.parse.transitionparser import TransitionParser
from nltk.tag.perceptron import AveragedPerceptron, PerceptronTagger


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    root.mkdir()
    monkeypatch.setattr(pathsec, "ENFORCE", True)
    monkeypatch.setattr(nltk.data, "path", [str(root.resolve())])
    monkeypatch.setattr(pathsec, "_ALLOWED_ROOTS_CACHE", None)
    monkeypatch.setattr(pathsec, "_LAST_DATA_PATHS", None)
    # Private system-temp directories can themselves be allowed roots. Stage
    # the attack destination under HOME so this tests a real sandbox escape.
    with TemporaryDirectory(prefix=".edmg-nltk-security-", dir=Path.home()) as directory:
        outside = Path(directory)
        with pytest.raises(PermissionError):
            pathsec.open(str(outside / "probe"), "w")
        yield root, outside


def test_perceptron_refuses_outside_reads_and_writes(sandbox):
    root, outside = sandbox
    model = AveragedPerceptron()
    model.weights = {"feature": {"NN": 1.0}}
    target = outside / "model.json"
    with pytest.raises(PermissionError):
        model.save(str(target))
    assert not target.exists()
    target.write_text('{"secret": {"NN": 7.0}}', encoding="utf-8")
    with pytest.raises(PermissionError):
        model.load(str(target))
    assert "secret" not in model.weights
    allowed = root / "model.json"
    model.save(str(allowed))
    restored = AveragedPerceptron()
    restored.load(str(allowed))
    assert restored.weights == model.weights


def test_tagger_refuses_outside_save_and_preserves_allowed_roundtrip(sandbox):
    root, outside = sandbox
    tagger = PerceptronTagger(load=False)
    tagger.model.weights = {"feature": {"NN": 1.0}}
    tagger.classes = {"NN"}
    tagger.tagdict = {}
    with pytest.raises(PermissionError):
        tagger.save_to_json(lang="eng", loc=str(outside / "tagger"))
    assert not (outside / "tagger").exists()
    allowed = root / "tagger"
    tagger.save_to_json(lang="eng", loc=str(allowed))
    restored = PerceptronTagger(load=False)
    restored.load_from_json("eng", str(allowed))
    assert restored.model.weights == tagger.model.weights


def test_maxent_refuses_outside_directory_and_keeps_allowed_save(sandbox):
    import numpy as np

    root, outside = sandbox
    target = outside / "parameters"
    with pytest.raises(PermissionError):
        save_maxent_params(np.array([0.5]), {}, ["positive"], {}, tab_dir=str(target))
    assert not target.exists()
    allowed = root / "parameters"
    save_maxent_params(np.array([0.5]), {}, ["positive"], {}, tab_dir=str(allowed))
    assert (allowed / "weights.txt").is_file()


def test_transition_parser_refuses_outside_model_before_unpickling(sandbox):
    _, outside = sandbox
    target = outside / "model.pickle"
    target.write_bytes(b"not a pickle")
    parser = TransitionParser("arc-standard")
    with pytest.raises(PermissionError):
        parser.parse([], str(target))


def test_textblob_sentiment_still_works():
    textblob = pytest.importorskip("textblob")
    assert textblob.TextBlob("I love this wonderful music").sentiment.polarity > 0
    assert textblob.TextBlob("I hate this terrible noise").sentiment.polarity < 0
