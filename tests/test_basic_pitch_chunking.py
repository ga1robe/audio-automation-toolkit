import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import mido

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import audio_toolkit


def test_large_basic_pitch_stem_is_chunked_and_midi_offsets_are_merged(tmp_path):
    chunk_requests = []

    class FakeSegment:
        @classmethod
        def from_file(cls, audio_path, start_second, duration):
            chunk_requests.append((audio_path, start_second, duration))
            duration_ms = {0.0: 1000, 1.0: 1000, 2.0: 500}[start_second]
            return cls(duration_ms)

        def __init__(self, duration_ms):
            self.duration_ms = duration_ms

        def __len__(self):
            return self.duration_ms

        def export(self, path, format):
            assert format == "wav"
            Path(path).touch()

    source_stem = tmp_path / "guitar.wav"
    source_stem.write_bytes(b"large stem")
    output_midi = tmp_path / "midi" / "guitar.mid"

    def fake_run(cmd, check):
        assert check is True
        assert Path(cmd[1]).name == "conversion_basicpitch.py"
        chunk_midi_path = Path(cmd[-1])
        chunk_midi_path.parent.mkdir(parents=True, exist_ok=True)

        midi = mido.MidiFile(type=1, ticks_per_beat=480)
        tempo_track = mido.MidiTrack()
        tempo_track.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))
        midi.tracks.append(tempo_track)

        notes_track = mido.MidiTrack()
        notes_track.append(mido.Message("note_on", note=60, velocity=100, time=0))
        notes_track.append(mido.Message("note_off", note=60, velocity=0, time=48))
        midi.tracks.append(notes_track)
        midi.save(str(chunk_midi_path))

    with (
        patch.dict(sys.modules, {"pydub": SimpleNamespace(AudioSegment=FakeSegment)}),
        patch.object(audio_toolkit, "BASIC_PITCH_MAX_STEM_SIZE_BYTES", 1),
        patch.object(audio_toolkit, "BASIC_PITCH_CHUNK_DURATION_MS", 1000),
        patch.object(audio_toolkit.subprocess, "run", side_effect=fake_run) as run,
    ):
        audio_toolkit.run_basic_pitch_with_chunking(source_stem, output_midi)

    assert run.call_count == 3
    assert chunk_requests == [
        (str(source_stem), 0.0, 1.0),
        (str(source_stem), 1.0, 1.0),
        (str(source_stem), 2.0, 1.0),
    ]

    merged = mido.MidiFile(output_midi)
    absolute_note_on_ticks = []
    absolute_tick = 0
    for message in merged.tracks[1]:
        absolute_tick += message.time
        if message.type == "note_on" and message.velocity:
            absolute_note_on_ticks.append(absolute_tick)
    assert absolute_note_on_ticks == [0, 960, 1920]


def test_pipeline_records_basic_pitch_failure_in_manifest(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "guitar.wav").touch()

    def fail_basic_pitch(cmd, check):
        assert check is True
        assert Path(cmd[1]).name == "conversion_basicpitch.py"
        Path(cmd[-1]).write_bytes(b"partial MIDI")
        raise audio_toolkit.subprocess.CalledProcessError(9, cmd)

    with (
        patch.object(
            audio_toolkit,
            "get_audio_metadata",
            return_value={
                "duration_seconds": 1.0,
                "sample_rate": 44100,
                "channels": 2,
            },
        ),
        patch.object(
            audio_toolkit.subprocess, "run", side_effect=fail_basic_pitch
        ),
    ):
        manifest = audio_toolkit.run_process_pipeline(
            input_dir, output_dir, stage="tf"
        )

    track_manifest = manifest["results"][0]
    assert track_manifest["status"] == "failed"
    assert track_manifest["midi"] == {}
    assert not (output_dir / "guitar" / "midi" / "guitar.mid").exists()
    assert track_manifest["warnings"] == [
        "Basic Pitch MIDI generation failed for guitar.wav (exit code 9)"
    ]
    assert {
        "level": "warning",
        "message": track_manifest["warnings"][-1],
    } in track_manifest["logs"]
