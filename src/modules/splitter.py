from __future__ import annotations

from pathlib import Path

DEFAULT_MAX_CHUNK_DURATION_MS = 5 * 60 * 1000


def split_dj_set_by_silence(
    input_path: Path,
    output_dir: Path,
    min_silence_len: int = 3000,
    silence_thresh: int = -40,
    max_chunk_duration_ms: int = DEFAULT_MAX_CHUNK_DURATION_MS,
) -> list[Path]:
    """
    Split audio at silence, then cap each exported chunk's duration.
    """
    if min_silence_len <= 0:
        raise ValueError("Minimum silence length must be greater than zero.")
    if max_chunk_duration_ms <= 0:
        raise ValueError("Maximum chunk duration must be greater than zero.")

    input_path = Path(input_path)
    if not input_path.is_file():
        raise FileNotFoundError(f"Audio file does not exist: {input_path}")

    from pydub import AudioSegment
    from pydub.silence import split_on_silence

    output_dir.mkdir(parents=True, exist_ok=True)
    split_files: list[Path] = []
    start_ms = 0

    print(f"Loading audio for splitting: {input_path.name}...", flush=True)
    while True:
        audio = AudioSegment.from_file(
            str(input_path),
            start_second=start_ms / 1000,
            duration=max_chunk_duration_ms / 1000,
        )
        audio_duration_ms = len(audio)
        if not audio_duration_ms:
            break

        print("Finding silence-based split points...", flush=True)
        silence_chunks = split_on_silence(
            audio,
            min_silence_len=min_silence_len,
            silence_thresh=silence_thresh,
            keep_silence=1000,
        )

        for chunk in silence_chunks:
            for chunk_start_ms in range(0, len(chunk), max_chunk_duration_ms):
                part = chunk[chunk_start_ms : chunk_start_ms + max_chunk_duration_ms]
                if not len(part):
                    continue

                chunk_name = output_dir / f"track_{len(split_files) + 1:02d}.wav"
                print(
                    f"Exporting {chunk_name.name} "
                    f"({len(part) / 1000:.1f}s)",
                    flush=True,
                )
                part.export(chunk_name, format="wav")
                split_files.append(chunk_name)

        del audio
        if audio_duration_ms < max_chunk_duration_ms:
            break
        start_ms += audio_duration_ms

    if not split_files:
        raise RuntimeError(f"No audio chunks were produced from {input_path}.")

    return split_files
