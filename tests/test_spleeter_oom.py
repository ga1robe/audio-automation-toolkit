import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import audio_toolkit


def test_spleeter_retries_all_chunks_after_oom_and_combines_each_stem(tmp_path):
    chunk_requests = []

    class FakeSegment:
        @classmethod
        def from_file(cls, _audio_path, start_second, duration):
            chunk_requests.append((start_second, duration))
            return cls(min(1000, max(0, 1500 - int(start_second * 1000))))

        def __init__(self, duration_ms):
            self.duration_ms = duration_ms

        def __len__(self):
            return self.duration_ms

        def export(self, path, format):
            assert format == "wav"
            Path(path).touch()

    expected_frames = {
        "vocals": [b"\x01\x00\x01\x00", b"\x02\x00\x02\x00"],
        "accompaniment": [b"\x03\x00\x03\x00", b"\x04\x00\x04\x00"],
    }

    def fake_spleeter(cmd, check, timeout):
        assert check is True
        assert timeout == audio_toolkit.SPLEETER_CHUNK_TIMEOUT_SECONDS
        chunk_path = Path(cmd[-1])
        chunk_index = int(chunk_path.stem.rsplit("_", 1)[1])
        model = cmd[cmd.index("-p") + 1]
        if model == "spleeter:5stems" and chunk_index == 1:
            raise audio_toolkit.subprocess.CalledProcessError(137, cmd)

        output_dir = Path(cmd[cmd.index("-o") + 1]) / chunk_path.stem
        output_dir.mkdir(parents=True)
        for stem_name, chunk_frames in expected_frames.items():
            with wave.open(str(output_dir / f"{stem_name}.wav"), "wb") as output:
                output.setnchannels(2)
                output.setsampwidth(2)
                output.setframerate(44100)
                output.writeframes(chunk_frames[chunk_index])

    source_path = tmp_path / "long_mix.mp3"
    stems_dir = tmp_path / "stems"
    with (
        patch.dict(sys.modules, {"pydub": SimpleNamespace(AudioSegment=FakeSegment)}),
        patch.object(audio_toolkit, "SPLEETER_CHUNK_DURATION_MS", 1000),
        patch.object(audio_toolkit.subprocess, "run", side_effect=fake_spleeter) as run,
    ):
        result = audio_toolkit.run_spleeter_with_fallback(
            source_path,
            stems_dir,
            5,
        )

    assert result == 2
    assert run.call_count == 4
    assert chunk_requests == [(0, 1), (1, 1)]
    for stem_name, chunk_frames in expected_frames.items():
        combined_path = stems_dir / "long_mix" / f"{stem_name}.wav"
        with wave.open(str(combined_path), "rb") as combined:
            assert combined.getnframes() == len(chunk_frames)
            assert combined.readframes(combined.getnframes()) == b"".join(chunk_frames)


def test_spleeter_retries_with_two_stems_after_chunk_timeout(tmp_path):
    class FakeSegment:
        @classmethod
        def from_file(cls, _audio_path, start_second, duration):
            return cls(500 if start_second == 0 else 0)

        def __init__(self, duration_ms):
            self.duration_ms = duration_ms

        def __len__(self):
            return self.duration_ms

        def export(self, path, format):
            assert format == "wav"
            Path(path).touch()

    def fake_spleeter(cmd, check, timeout):
        assert check is True
        assert timeout == audio_toolkit.SPLEETER_CHUNK_TIMEOUT_SECONDS
        chunk_path = Path(cmd[-1])
        model = cmd[cmd.index("-p") + 1]
        if model == "spleeter:5stems":
            raise audio_toolkit.subprocess.TimeoutExpired(cmd, timeout)

        output_dir = Path(cmd[cmd.index("-o") + 1]) / chunk_path.stem
        output_dir.mkdir(parents=True)
        for stem_name in ("vocals", "accompaniment"):
            with wave.open(str(output_dir / f"{stem_name}.wav"), "wb") as output:
                output.setnchannels(2)
                output.setsampwidth(2)
                output.setframerate(44100)
                output.writeframes(b"\x01\x00\x01\x00")

    source_path = tmp_path / "long_mix.mp3"
    stems_dir = tmp_path / "stems"
    with (
        patch.dict(sys.modules, {"pydub": SimpleNamespace(AudioSegment=FakeSegment)}),
        patch.object(audio_toolkit, "SPLEETER_CHUNK_DURATION_MS", 1000),
        patch.object(audio_toolkit.subprocess, "run", side_effect=fake_spleeter) as run,
    ):
        result = audio_toolkit.run_spleeter_with_fallback(
            source_path,
            stems_dir,
            5,
        )

    assert result == 2
    assert run.call_count == 2
    assert sorted(path.name for path in (stems_dir / "long_mix").glob("*.wav")) == [
        "accompaniment.wav",
        "vocals.wav",
    ]


def test_pipeline_runs_analysis_after_spleeter_stems_are_ready(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source_path = input_dir / "mix.wav"
    source_path.touch()

    def fake_spleeter(_audio_path, stems_dir, _stems_count, _debug_steps):
        track_stems_dir = stems_dir / "mix"
        track_stems_dir.mkdir(parents=True)
        (track_stems_dir / "vocals.wav").touch()
        (track_stems_dir / "accompaniment.wav").touch()
        return 2

    def fake_run(cmd, check):
        assert check is True
        if Path(cmd[1]).name == "analysis.py":
            analysis_path = Path(cmd[cmd.index("--output") + 1])
            analysis_path.write_text('{"tempo": 120}', encoding="utf-8")

    with (
        patch.object(audio_toolkit, "run_spleeter_with_fallback", side_effect=fake_spleeter),
        patch.object(audio_toolkit.subprocess, "run", side_effect=fake_run) as run,
    ):
        manifest = audio_toolkit.run_process_pipeline(
            input_dir,
            output_dir,
            stage="base",
            skip_asr=True,
        )

    assert run.call_count == 1
    assert manifest["results"][0]["analysis"]["tempo"] == 120
    assert set(manifest["results"][0]["stems"]) == {"vocals", "accompaniment"}


def test_pipeline_continues_when_spectrogram_is_killed(tmp_path, capsys):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    source_path = input_dir / "mix.wav"
    source_path.touch()

    def fake_spleeter(_audio_path, stems_dir, _stems_count, _debug_steps):
        track_stems_dir = stems_dir / "mix"
        track_stems_dir.mkdir(parents=True)
        (track_stems_dir / "other.wav").touch()
        return 2

    def fake_run(cmd, check):
        assert check is True
        if Path(cmd[1]).name == "analysis.py":
            analysis_path = Path(cmd[cmd.index("--output") + 1])
            analysis_path.write_text('{"tempo": 120}', encoding="utf-8")
        elif Path(cmd[1]).name == "spectrogram.py":
            output_path = Path(cmd[cmd.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"partial image")
            raise audio_toolkit.subprocess.CalledProcessError(-9, cmd)

    with (
        patch.object(audio_toolkit, "run_spleeter_with_fallback", side_effect=fake_spleeter),
        patch.object(audio_toolkit.subprocess, "run", side_effect=fake_run),
    ):
        manifest = audio_toolkit.run_process_pipeline(
            input_dir,
            output_dir,
            stage="base",
            spectro_bool=True,
            skip_asr=True,
        )

    track_manifest = manifest["results"][0]
    spectrogram_path = output_dir / "mix" / "spectrograms" / "spectrogram.other.png"
    assert track_manifest["analysis"]["tempo"] == 120
    assert track_manifest["stems"]["other"]
    assert track_manifest["spectrograms"] == {}
    assert not spectrogram_path.exists()
    assert "skipping it" in capsys.readouterr().err


def test_choose_recovery_stems_uses_lower_model_on_oom():
    assert audio_toolkit.choose_recovery_stems(5) == 2
    assert audio_toolkit.choose_recovery_stems(4) == 2
    assert audio_toolkit.choose_recovery_stems(2) is None


def test_normalize_asr_language_supports_us_alias():
    assert audio_toolkit.normalize_asr_language("us") == "en"
    assert audio_toolkit.normalize_asr_language("en-US") == "en"
    assert audio_toolkit.normalize_asr_language("pl") == "pl"


def test_normalize_asr_language_supports_automatic_detection():
    assert audio_toolkit.normalize_asr_language("None") is None
    assert audio_toolkit.normalize_asr_language("auto") is None
