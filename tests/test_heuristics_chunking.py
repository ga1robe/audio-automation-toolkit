import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import mido

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import audio_toolkit


def test_large_heuristic_stem_is_chunked_and_midi_offsets_are_merged(tmp_path):
    chunk_requests = []

    class FakeSegment:
        @classmethod
        def from_file(cls, _audio_path, start_second, duration):
            chunk_requests.append((_audio_path, start_second, duration))
            duration_ms = {0.0: 1000, 1.0: 1000, 2.0: 500}[start_second]
            return cls(duration_ms)

        def __init__(self, duration_ms):
            self.duration_ms = duration_ms

        def __len__(self):
            return self.duration_ms

        def export(self, path, format):
            assert format == "wav"
            Path(path).touch()

    source_stem = tmp_path / "drums.wav"
    source_stem.write_bytes(b"large stem")
    output_midi = tmp_path / "midi" / "drums.mid"

    def fake_run(cmd, check):
        assert check is True
        assert cmd[cmd.index("--type") + 1] == "drums"
        assert cmd[cmd.index("--tempo") + 1] == "120.0"
        chunk_midi_path = Path(cmd[cmd.index("--output") + 1])
        chunk_midi_path.parent.mkdir(parents=True, exist_ok=True)

        midi = mido.MidiFile(type=1, ticks_per_beat=480)
        tempo_track = mido.MidiTrack()
        tempo_track.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))
        midi.tracks.append(tempo_track)

        notes_track = mido.MidiTrack()
        notes_track.append(mido.Message("note_on", note=36, velocity=100, time=0))
        notes_track.append(mido.Message("note_off", note=36, velocity=0, time=48))
        midi.tracks.append(notes_track)
        midi.save(str(chunk_midi_path))

    with (
        patch.dict(sys.modules, {"pydub": SimpleNamespace(AudioSegment=FakeSegment)}),
        patch.object(audio_toolkit, "HEURISTICS_MAX_STEM_SIZE_BYTES", 1),
        patch.object(audio_toolkit, "HEURISTICS_CHUNK_DURATION_MS", 1000),
        patch.object(audio_toolkit.subprocess, "run", side_effect=fake_run) as run,
    ):
        audio_toolkit.run_heuristics_with_chunking(
            "drums", source_stem, output_midi, tempo_bpm=120.0
        )

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


def test_small_heuristic_stem_runs_without_chunking(tmp_path):
    source_stem = tmp_path / "bass.wav"
    source_stem.touch()
    output_midi = tmp_path / "midi" / "bass.mid"

    with (
        patch.object(audio_toolkit, "HEURISTICS_MAX_STEM_SIZE_BYTES", 1),
        patch.object(audio_toolkit.subprocess, "run") as run,
    ):
        audio_toolkit.run_heuristics_with_chunking(
            "bass", source_stem, output_midi, tempo_bpm=100.0
        )

    run.assert_called_once()
    command = run.call_args.args[0]
    assert command[command.index("--input") + 1] == str(source_stem)
    assert command[command.index("--output") + 1] == str(output_midi)
