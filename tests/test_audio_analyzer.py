from enhanced_deforum_music_generator.config.config_system import AudioConfig
from enhanced_deforum_music_generator.core.audio_analyzer import AudioAnalyzer


def test_audio_analyzer_runs_on_committed_test_audio_file(test_audio_file):
    analyzer = AudioAnalyzer(AudioConfig(max_duration=5))
    results = analyzer.analyze(test_audio_file)

    assert "beats" in results
    assert "energy" in results
    assert isinstance(results["energy"], list)
    assert 4.5 <= results["duration"] <= 5.1
    assert results["sample_rate"] == 22050
    assert len(results["energy"]) > 100
    assert max(results["energy"]) > 0
