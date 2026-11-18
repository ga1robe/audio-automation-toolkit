import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "modules"))

import analysis
import splitter


def test_silence_splitter_caps_chunk_duration(tmp_path):
    exported_durations = []

    class FakeSegment:
        durations = iter((1500, 0))

        @classmethod
        def from_file(cls, _path, start_second, duration):
            assert start_second >= 0
            assert duration == 0.6
            return cls(next(cls.durations))

        def __init__(self, duration_ms):
            self.duration_ms = duration_ms

        def __len__(self):
            return self.duration_ms

        def __getitem__(self, interval):
            return FakeSegment(
                max(0, min(interval.stop, len(self)) - interval.start)
            )

        def export(self, path, format):
            assert format == "wav"
            exported_durations.append(self.duration_ms)
            Path(path).touch()

    fake_pydub = SimpleNamespace(AudioSegment=FakeSegment)
    fake_pydub_silence = SimpleNamespace(
        split_on_silence=lambda audio, **_kwargs: [audio]
    )
    input_path = tmp_path / "long_mix.wav"
    input_path.touch()

    with patch.dict(
        sys.modules,
        {"pydub": fake_pydub, "pydub.silence": fake_pydub_silence},
    ):
        chunks = splitter.split_dj_set_by_silence(
            input_path,
            tmp_path / "chunks",
            max_chunk_duration_ms=600,
        )

    assert [chunk.name for chunk in chunks] == [
        "track_01.wav",
        "track_02.wav",
        "track_03.wav",
    ]
    assert exported_durations == [600, 600, 300]


def test_audio_analysis_returns_results_for_each_split_segment(tmp_path):
    source_path = tmp_path / "long_mix.wav"

    def fake_split(_source_path, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        chunks = [output_dir / "track_01.wav", output_dir / "track_02.wav"]
        for chunk in chunks:
            chunk.touch()
        return chunks

    def fake_analysis(chunk_path, spectrogram_path):
        return {
            "tempo": 100.0 if Path(chunk_path).name == "track_01.wav" else 120.0,
            "spectrogram": spectrogram_path,
        }

    with (
        patch.object(analysis, "split_dj_set_by_silence", side_effect=fake_split),
        patch.object(analysis, "_analyze_audio_file", side_effect=fake_analysis),
    ):
        results = analysis.analyze_audio(
            str(source_path),
            str(tmp_path / "analysis.png"),
        )

    assert results == [
        {
            "tempo": 100.0,
            "spectrogram": str(tmp_path / "analysis.segment_01.png"),
            "file": "long_mix.wav",
            "segment": "track_01.wav",
        },
        {
            "tempo": 120.0,
            "spectrogram": str(tmp_path / "analysis.segment_02.png"),
            "file": "long_mix.wav",
            "segment": "track_02.wav",
        },
    ]
    output_path = tmp_path / "analysis.json"
    analysis.write_json(results, str(output_path))
    assert json.loads(output_path.read_text(encoding="utf-8")) == results


def test_audio_analysis_keeps_single_segment_result_as_object(tmp_path):
    source_path = tmp_path / "short_mix.wav"
    chunk_path = tmp_path / "track_01.wav"

    with (
        patch.object(
            analysis,
            "split_dj_set_by_silence",
            return_value=[chunk_path],
        ),
        patch.object(
            analysis,
            "_analyze_audio_file",
            return_value={"tempo": 110.0},
        ),
    ):
        results = analysis.analyze_audio(str(source_path))

    assert results == {"tempo": 110.0, "file": "short_mix.wav"}
