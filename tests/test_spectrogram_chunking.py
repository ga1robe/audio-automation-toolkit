import json
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "modules"))

import audio_toolkit
import spectrogram


def _write_sine_wav(path: Path, duration_s: float = 2.5, sr: int = 22050) -> None:
    t = np.linspace(0.0, duration_s, int(sr * duration_s), endpoint=False)
    samples = 0.25 * np.sin(2.0 * np.pi * 220.0 * t)
    sf.write(str(path), samples, sr)


def test_full_stage_combines_chunks_with_recalculated_full_time_axis(tmp_path):
    wav_path = tmp_path / "bass.wav"
    _write_sine_wav(wav_path, duration_s=2.5, sr=22050)

    specs_json = tmp_path / "specs.json"
    specs_json.write_text(
        json.dumps(
            [
                {"offset_seconds": 0.0, "duration_seconds": 1.0},
                {"offset_seconds": 1.0, "duration_seconds": 1.0},
                {"offset_seconds": 2.0, "duration_seconds": 0.5},
            ]
        ),
        encoding="utf-8",
    )
    out_png = tmp_path / "full_spectrogram.png"

    spectrogram.render_combined_full_axis_spectrogram(
        wav_path=wav_path,
        chunk_specs_json=specs_json,
        img_path=out_png,
        sr=22050,
        n_fft=512,
        hop_length=256,
    )

    assert out_png.is_file()
    assert out_png.stat().st_size > 0
    with Image.open(out_png) as img:
        assert img.width > 0 and img.height > 0


def test_non_full_stage_stitches_tiles_horizontally(tmp_path):
    tile1 = tmp_path / "t1.png"
    tile2 = tmp_path / "t2.png"
    Image.new("RGB", (120, 80), color=(255, 0, 0)).save(tile1)
    Image.new("RGB", (150, 80), color=(0, 255, 0)).save(tile2)

    out_png = tmp_path / "stitched.png"
    spectrogram.combine_spectrogram_tiles_horizontal([tile1, tile2], out_png)

    assert out_png.is_file()
    with Image.open(out_png) as img:
        assert img.size == (270, 80)


def test_run_spectrogram_with_chunking_uses_full_axis_for_full_stage(tmp_path):
    stem_file = tmp_path / "drums.wav"
    stem_file.write_bytes(b"x" * 64)
    out_spectro = tmp_path / "out" / "spectrogram.drums.png"

    recorded_cmds: list[list[str]] = []

    def fake_run(cmd, check):
        assert check is True
        recorded_cmds.append([str(c) for c in cmd])
        out_arg = Path(cmd[cmd.index("--output") + 1])
        out_arg.parent.mkdir(parents=True, exist_ok=True)
        out_arg.write_bytes(b"png")

    with (
        patch.object(audio_toolkit, "SPECTROGRAM_MAX_STEM_SIZE_BYTES", 10),
        patch.object(audio_toolkit, "SPECTROGRAM_CHUNK_DURATION_MS", 1000),
        patch.object(
            audio_toolkit,
            "get_audio_metadata",
            return_value={"duration_seconds": 2.5, "sample_rate": 22050, "channels": 1},
        ),
        patch.object(audio_toolkit.subprocess, "run", side_effect=fake_run),
    ):
        audio_toolkit.run_spectrogram_with_chunking(
            stem_file, out_spectro, stage="full"
        )

    assert out_spectro.is_file()
    assert len(recorded_cmds) == 1
    assert "--combine-full-axis-from-chunks" in recorded_cmds[0]


def test_run_spectrogram_with_chunking_uses_bare_tiles_for_base_stage(tmp_path):
    stem_file = tmp_path / "drums.wav"
    stem_file.write_bytes(b"x" * 64)
    out_spectro = tmp_path / "out" / "spectrogram.drums.png"

    recorded_cmds: list[list[str]] = []

    def fake_run(cmd, check):
        assert check is True
        recorded_cmds.append([str(c) for c in cmd])
        out_arg = Path(cmd[cmd.index("--output") + 1])
        out_arg.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (50, 40), color=(10, 20, 30)).save(out_arg)

    with (
        patch.object(audio_toolkit, "SPECTROGRAM_MAX_STEM_SIZE_BYTES", 10),
        patch.object(audio_toolkit, "SPECTROGRAM_CHUNK_DURATION_MS", 1000),
        patch.object(
            audio_toolkit,
            "get_audio_metadata",
            return_value={"duration_seconds": 2.0, "sample_rate": 22050, "channels": 1},
        ),
        patch.object(audio_toolkit.subprocess, "run", side_effect=fake_run),
    ):
        audio_toolkit.run_spectrogram_with_chunking(
            stem_file, out_spectro, stage="base"
        )

    assert out_spectro.is_file()
    assert len(recorded_cmds) == 3  # 2 kafelki + 1 scalanie --stitch-tiles
    assert "--bare-panel" in recorded_cmds[0]
    assert "--bare-panel" in recorded_cmds[1]
    assert "--stitch-tiles" in recorded_cmds[2]
