from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_CHUNK_DURATION_MS = 5 * 60 * 1000


@dataclass(frozen=True)
class AudioChunk:
    path: Path
    start_ms: int
    end_ms: int


def split_dj_set_by_silence(
    input_path: Path,
    output_dir: Path,
    min_silence_len: int = 3000,
    silence_thresh: int = -40,
    max_chunk_duration_ms: int = DEFAULT_MAX_CHUNK_DURATION_MS,
) -> list[Path]:
    return [
        chunk.path
        for chunk in split_dj_set_by_silence_with_timestamps(
            input_path,
            output_dir,
            min_silence_len,
            silence_thresh,
            max_chunk_duration_ms,
        )
    ]


def split_dj_set_by_silence_with_timestamps(
    input_path: Path,
    output_dir: Path,
    min_silence_len: int = 3000,
    silence_thresh: int = -40,
    max_chunk_duration_ms: int = DEFAULT_MAX_CHUNK_DURATION_MS,
) -> list[AudioChunk]:
    """
    Split audio at silence, cap chunk duration, and retain source time ranges.
    """
    if min_silence_len <= 0:
        raise ValueError("Minimum silence length must be greater than zero.")
    if max_chunk_duration_ms <= 0:
        raise ValueError("Maximum chunk duration must be greater than zero.")

    input_path = Path(input_path)
    if not input_path.is_file():
        raise FileNotFoundError(f"Audio file does not exist: {input_path}")

    from pydub import AudioSegment
    from pydub.silence import detect_nonsilent

    output_dir.mkdir(parents=True, exist_ok=True)
    split_chunks: list[AudioChunk] = []
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
        nonsilent_ranges = detect_nonsilent(
            audio,
            min_silence_len=min_silence_len,
            silence_thresh=silence_thresh,
        )

        split_ranges = [
            [max(0, start - 1000), min(audio_duration_ms, end + 1000)]
            for start, end in nonsilent_ranges
        ]
        for index in range(len(split_ranges) - 1):
            current_end = split_ranges[index][1]
            next_start = split_ranges[index + 1][0]
            if next_start < current_end:
                midpoint = (current_end + next_start) // 2
                split_ranges[index][1] = midpoint
                split_ranges[index + 1][0] = midpoint

        for range_start_ms, range_end_ms in split_ranges:
            chunk = audio[range_start_ms:range_end_ms]
            for chunk_start_ms in range(0, len(chunk), max_chunk_duration_ms):
                part = chunk[chunk_start_ms : chunk_start_ms + max_chunk_duration_ms]
                if not len(part):
                    continue

                chunk_name = output_dir / f"track_{len(split_chunks) + 1:02d}.wav"
                print(
                    f"Exporting {chunk_name.name} "
                    f"({len(part) / 1000:.1f}s)",
                    flush=True,
                )
                part.export(chunk_name, format="wav")
                part_start_ms = start_ms + range_start_ms + chunk_start_ms
                split_chunks.append(
                    AudioChunk(
                        path=chunk_name,
                        start_ms=part_start_ms,
                        end_ms=part_start_ms + len(part),
                    )
                )

        del audio
        if audio_duration_ms < max_chunk_duration_ms:
            break
        start_ms += audio_duration_ms

    if not split_chunks:
        raise RuntimeError(f"No audio chunks were produced from {input_path}.")

    return split_chunks
