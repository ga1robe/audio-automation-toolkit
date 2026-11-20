import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

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
        detect_nonsilent=lambda audio, **_kwargs: [[0, len(audio)]]
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


def test_silence_splitter_retains_source_time_ranges(tmp_path):
    class FakeSegment:
        durations = iter((1500, 0))

        @classmethod
        def from_file(cls, _path, start_second, duration):
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
            Path(path).touch()

    input_path = tmp_path / "long_mix.wav"
    input_path.touch()
    fake_pydub = SimpleNamespace(AudioSegment=FakeSegment)
    fake_pydub_silence = SimpleNamespace(
        detect_nonsilent=lambda _audio, **_kwargs: [[1200, 1400]]
    )

    with patch.dict(
        sys.modules,
        {"pydub": fake_pydub, "pydub.silence": fake_pydub_silence},
    ):
        chunks = splitter.split_dj_set_by_silence_with_timestamps(
            input_path,
            tmp_path / "timed_chunks",
            max_chunk_duration_ms=600,
        )

    assert [(chunk.start_ms, chunk.end_ms) for chunk in chunks] == [
        (200, 800),
        (800, 1400),
        (1400, 1500),
    ]


def test_audio_analysis_returns_results_for_each_split_segment(tmp_path):
    source_path = tmp_path / "long_mix.wav"

    def fake_split(_source_path, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        chunks = [
            splitter.AudioChunk(output_dir / "track_01.wav", 0, 1000),
            splitter.AudioChunk(output_dir / "track_02.wav", 1000, 2000),
        ]
        for chunk in chunks:
            chunk.path.touch()
        return chunks

    def fake_analysis(chunk_path, spectrogram_path):
        return {
            "tempo": 100.0 if Path(chunk_path).name == "track_01.wav" else 120.0,
            "spectrogram": spectrogram_path,
            "_voiced_pitches": [],
        }

    with (
        patch.object(
            analysis,
            "split_dj_set_by_silence_with_timestamps",
            side_effect=fake_split,
        ),
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
            "segment": {"start_seconds": 0.0, "end_seconds": 1.0},
        },
        {
            "tempo": 120.0,
            "spectrogram": str(tmp_path / "analysis.segment_02.png"),
            "file": "long_mix.wav",
            "segment": {"start_seconds": 1.0, "end_seconds": 2.0},
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
            "split_dj_set_by_silence_with_timestamps",
            return_value=[splitter.AudioChunk(chunk_path, 0, 1000)],
        ),
        patch.object(
            analysis,
            "_analyze_audio_file",
            return_value={"tempo": 110.0},
        ),
    ):
        results = analysis.analyze_audio(str(source_path))

    assert results == {
        "tempo": 110.0,
        "file": "short_mix.wav",
        "segment": {"start_seconds": 0.0, "end_seconds": 1.0},
    }


def test_audio_analysis_merges_adjacent_metadata_and_recomputes_bass_median(tmp_path):
    source_path = tmp_path / "long_mix.wav"
    chunk_paths = [
        tmp_path / "track_01.wav",
        tmp_path / "track_02.wav",
        tmp_path / "track_03.wav",
    ]
    chunks = [
        splitter.AudioChunk(chunk_paths[0], 0, 1000),
        splitter.AudioChunk(chunk_paths[1], 1000, 2000),
        splitter.AudioChunk(chunk_paths[2], 2000, 3000),
    ]
    analyses = {
        "track_01.wav": {"tempo": 100.0, "_voiced_pitches": [100.0, 200.0, 300.0]},
        "track_02.wav": {"tempo": 100.0, "_voiced_pitches": [1000.0]},
        "track_03.wav": {"tempo": 110.0, "_voiced_pitches": [400.0]},
    }

    with (
        patch.object(
            analysis,
            "split_dj_set_by_silence_with_timestamps",
            return_value=chunks,
        ),
        patch.object(
            analysis,
            "_analyze_audio_file",
            side_effect=lambda path, _spectrogram: analyses[Path(path).name],
        ),
    ):
        results = analysis.analyze_audio(str(source_path))

    assert isinstance(results, list)
    assert len(results) == 2
    assert results[0]["segment"] == {
        "start_seconds": 0.0,
        "end_seconds": 2.0,
    }
    assert results[0]["bass_estimate"] == {
        "median_hz": 250.0,
        "median_midi": int(round(analysis.librosa.hz_to_midi(250.0))),
    }
    assert results[1]["segment"] == {
        "start_seconds": 2.0,
        "end_seconds": 3.0,
    }
    assert all("_voiced_pitches" not in result for result in results)


def test_structural_change_detection_uses_full_mix_spectral_novelty(tmp_path):
    source_path = tmp_path / "continuous_mix.wav"
    novelty = np.zeros(2000)
    novelty[500] = 4.0
    novelty[1500] = 8.0

    with (
        patch.object(
            analysis.librosa,
            "load",
            return_value=(np.ones(22050), 22050),
        ) as load_audio,
        patch.object(
            analysis.librosa.onset,
            "onset_strength",
            return_value=novelty,
        ) as onset_strength,
        patch.object(
            analysis.librosa.util,
            "peak_pick",
            return_value=np.array([500, 1500]),
        ),
    ):
        result = analysis.detect_structural_changes(str(source_path))

    load_audio.assert_called_once_with(
        str(source_path),
        sr=analysis.STRUCTURAL_NOVELTY_SAMPLE_RATE,
        mono=True,
    )
    onset_strength.assert_called_once()
    assert result["method"] == "librosa.onset.onset_strength"
    smoothing_frames = round(
        analysis.STRUCTURAL_NOVELTY_SMOOTHING_SECONDS
        * 22050
        / analysis.STRUCTURAL_NOVELTY_HOP_LENGTH
    )
    assert result["changes"] == [
        {
            "timestamp_seconds": round(
                500 * analysis.STRUCTURAL_NOVELTY_HOP_LENGTH / 22050, 3
            ),
            "novelty_score": round(4 / smoothing_frames, 6),
        },
        {
            "timestamp_seconds": round(
                1500 * analysis.STRUCTURAL_NOVELTY_HOP_LENGTH / 22050, 3
            ),
            "novelty_score": round(8 / smoothing_frames, 6),
        },
    ]
