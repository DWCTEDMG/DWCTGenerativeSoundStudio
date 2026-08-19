import platform


def test_audio_analyzer_runs_on_committed_test_audio_file(test_audio_file):
    if platform.system().strip().lower() == "windows":
        # The production Windows route deliberately avoids Librosa's native
        # Numba/llvmlite JIT because failures there terminate the interpreter
        # before Python can catch them. Exercise the same safe analyzer that
        # the Studio application uses on Windows.
        from edmg_studio_backend.services.safe_audio_analysis import analyze_audio_ffmpeg_numpy

        results = analyze_audio_ffmpeg_numpy(test_audio_file, source="windows_test_path")
        duration = results["duration_s"]
        expected_duration_range = (250.0, 260.0)
        assert results["analysis_backend"] == "ffmpeg_numpy"
        assert results["analysis_source"] == "windows_test_path"
    else:
        from enhanced_deforum_music_generator.config.config_system import AudioConfig
        from enhanced_deforum_music_generator.core.audio_analyzer import AudioAnalyzer

        analyzer = AudioAnalyzer(AudioConfig(max_duration=5))
        results = analyzer.analyze(test_audio_file)
        duration = results["duration"]
        expected_duration_range = (4.5, 5.1)

    assert "beats" in results
    assert "energy" in results
    assert isinstance(results["energy"], list)
    assert expected_duration_range[0] <= duration <= expected_duration_range[1]
    assert results["sample_rate"] == 22050
    assert len(results["energy"]) > 100
    assert max(results["energy"]) > 0
