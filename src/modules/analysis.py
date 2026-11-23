#!/usr/bin/env python3
import sys
import json
import argparse
import numpy as np
import librosa
#import tkinter as tk
from pathlib import Path
from tempfile import TemporaryDirectory

from splitter import split_dj_set_by_silence_with_timestamps

STRUCTURAL_NOVELTY_SAMPLE_RATE = 22050
STRUCTURAL_NOVELTY_HOP_LENGTH = 512
STRUCTURAL_NOVELTY_SMOOTHING_SECONDS = 3.0
STRUCTURAL_NOVELTY_MIN_GAP_SECONDS = 30.0


def _analyze_audio_file(file_path: str) -> dict:
    """Load an audio file and return its basic analysis metadata."""
    y, sr = librosa.load(file_path, sr=None, mono=True)
    
    # tempo
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    
    # tonacja (klucz)
    chroma = librosa.feature.chroma_stft(y=y, sr=sr)
    key_idx = int(np.argmax(np.mean(chroma, axis=1)))

    # miara taktu – na razie stała 4/4
    measure = "4/4"
    
    # nazwy tonacji (durowe + molowe)
    key_names = [
        'C Major', 'C# Major', 'D Major', 'D# Major', 'E Major', 'F Major',
        'F# Major', 'G Major', 'G# Major', 'A Major', 'A# Major', 'B Major',
        'C Minor', 'C# Minor', 'D Minor', 'D# Minor', 'E Minor', 'F Minor',
        'F# Minor', 'G Minor', 'G# Minor', 'A Minor', 'A# Minor', 'B Minor'
    ]
    tonality = key_names[key_idx]
    
    # BASS ESTIMATE: prosty oszacowanie linii basu przez librosa.pyin (fokus niskie freq)
    bass_estimate = None
    voiced_pitches = np.array([], dtype=float)
    try:
        fmin = 40.0
        fmax = 400.0
        hop_length = 256
        pitches, voiced_flags, _ = librosa.pyin(y, fmin=fmin, fmax=fmax, sr=sr, hop_length=hop_length)
        # weź częstość najczęściej występującą (modal pitch) spośród voiced frames
        voiced_pitches = pitches[~np.isnan(pitches)]
        if voiced_pitches.size:
            median_hz = float(np.median(voiced_pitches))
            median_midi = int(round(librosa.hz_to_midi(median_hz)))
            bass_estimate = {
                "median_hz": median_hz,
                "median_midi": median_midi,
            }
    except Exception:
        bass_estimate = None
    
    return {
        "tempo": float(tempo),
        "key_index": int(key_idx),
        "measure": measure,
        "tonality": tonality,
        "file": str(Path(file_path).name),
        "bass_estimate": bass_estimate,
        "_voiced_pitches": voiced_pitches,
    }


def analyze_audio(file_path: str) -> dict | list[dict]:
    """Analyze silence-separated, duration-capped chunks of the source audio."""
    source_path = Path(file_path)
    with TemporaryDirectory(prefix="audio-analysis-") as temp_dir:
        chunks = split_dj_set_by_silence_with_timestamps(
            source_path, Path(temp_dir)
        )
        analyses: list[dict] = []

        for chunk in chunks:
            result = _analyze_audio_file(str(chunk.path))
            result["file"] = source_path.name
            result.setdefault("_voiced_pitches", np.array([], dtype=float))
            result["segment"] = {
                "start_seconds": chunk.start_ms / 1000,
                "end_seconds": chunk.end_ms / 1000,
            }
            analyses.append(result)

    merged_analyses: list[dict] = []
    for result in analyses:
        if merged_analyses and _same_analysis_metadata(
            merged_analyses[-1], result
        ):
            previous = merged_analyses[-1]
            previous["_voiced_pitches"] = np.concatenate(
                (previous["_voiced_pitches"], result["_voiced_pitches"])
            )
            previous["segment"]["end_seconds"] = result["segment"]["end_seconds"]
            _update_bass_estimate(previous)
        else:
            merged_analyses.append(result)

    for result in merged_analyses:
        result.pop("_voiced_pitches", None)
    return merged_analyses[0] if len(merged_analyses) == 1 else merged_analyses


def detect_structural_changes(file_path: str) -> dict:
    """Detect major spectral-flux changes across the complete source audio."""
    y, sr = librosa.load(
        file_path,
        sr=STRUCTURAL_NOVELTY_SAMPLE_RATE,
        mono=True,
    )
    if not y.size:
        raise ValueError(f"Audio file is empty: {file_path}")

    hop_length = STRUCTURAL_NOVELTY_HOP_LENGTH
    novelty = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
    if not novelty.size:
        return {
            "method": "librosa.onset.onset_strength",
            "sample_rate": sr,
            "hop_length": hop_length,
            "changes": [],
        }

    smoothing_frames = max(
        1,
        min(
            novelty.size,
            int(round(STRUCTURAL_NOVELTY_SMOOTHING_SECONDS * sr / hop_length)),
        ),
    )
    smoothed_novelty = np.convolve(
        novelty,
        np.ones(smoothing_frames, dtype=float) / smoothing_frames,
        mode="same",
    )
    local_frames = max(1, int(round(2.0 * sr / hop_length)))
    average_frames = max(1, int(round(10.0 * sr / hop_length)))
    peak_frames = librosa.util.peak_pick(
        smoothed_novelty,
        pre_max=local_frames,
        post_max=local_frames,
        pre_avg=average_frames,
        post_avg=average_frames,
        delta=max(float(np.std(smoothed_novelty)) * 0.5, 1e-8),
        wait=max(
            1,
            int(round(STRUCTURAL_NOVELTY_MIN_GAP_SECONDS * sr / hop_length)),
        ),
    )

    return {
        "method": "librosa.onset.onset_strength",
        "sample_rate": sr,
        "hop_length": hop_length,
        "changes": [
            {
                "timestamp_seconds": round(float(frame * hop_length / sr), 3),
                "novelty_score": round(float(smoothed_novelty[frame]), 6),
            }
            for frame in peak_frames
        ],
    }


def _same_analysis_metadata(first: dict, second: dict) -> bool:
    """Compare fields that define analysis identity, excluding bass estimates."""
    metadata_keys = ("tempo", "key_index", "measure", "tonality", "file")
    return all(first.get(key) == second.get(key) for key in metadata_keys)


def _update_bass_estimate(result: dict) -> None:
    voiced_pitches = result["_voiced_pitches"]
    if voiced_pitches.size:
        median_hz = float(np.median(voiced_pitches))
        result["bass_estimate"] = {
            "median_hz": median_hz,
            "median_midi": int(round(librosa.hz_to_midi(median_hz))),
        }
    else:
        result["bass_estimate"] = None
    
def show_window(results: dict | list[dict]) -> None:
    """Wyświetla wyniki w oknie Tkinter."""
    """
    root = tk.Tk()
    root.title("Wyniki analizy audio")
    root.geometry("320x240")
    
    tk.Label(root, text=f"Tempo: {results['tempo']} BPM").pack(pady=6)
    tk.Label(root, text=f"Key index: {results['key_index']}").pack(pady=6)
    tk.Label(root, text=f"Measure: {results['measure']}").pack(pady=6)
    tk.Label(root, text=f"Tonality: {results['tonality']}").pack(pady=6)
    if results.get("bass_estimate"):
        b = results["bass_estimate"]
        tk.Label(root, text=f"Bass median: {b['median_midi']} (MIDI), {b['median_hz']:.1f} Hz").pack(pady=6)
    
    tk.Button(root, text="Zamknij", command=root.destroy).pack(pady=12)
    root.mainloop()
    """
    
def write_json(results: dict | list[dict], out_path: str) -> None:
    """Write analysis results as JSON."""
    path = Path(out_path)
    with path.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="analysis.py",
        description="Wyodrębnia metadane (tempo, tonacja, miara taktu) z pliku audio.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "audio_file",
        nargs="?",
        help="Ścieżka do pliku audio, który ma zostać przeanalizowany.",
    )
    parser.add_argument(
        "--show-window",
        action="store_true",
        help="Wyświetla wyniki w oknie graficznym (Tkinter).",
    )
    parser.add_argument(
        "--show",
        "--show-results",
        dest="show_cli",
        action="store_true",
        help="Wypisuje wyniki w konsoli.",
    )
    parser.add_argument(
        "--output",
        "--output-path",
        dest="output_path",
        metavar="FILE",
        help="Zapisuje wyniki w formacie JSON do podanego pliku.",
    )
    parser.add_argument(
        "--novelty-output",
        metavar="FILE",
        help="Zapisuje wykryte zmiany strukturalne do pliku JSON.",
    )
    return parser
    
def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    
    if not args.audio_file:
        parser.print_help()
        sys.exit(0)
        
    results = analyze_audio(args.audio_file)
    if args.novelty_output:
        write_json(
            detect_structural_changes(args.audio_file),
            args.novelty_output,
        )
    
    if args.show_cli:
        entries = results if isinstance(results, list) else [results]
        for index, entry in enumerate(entries, start=1):
            label = f"Segment {index}: " if len(entries) > 1 else ""
            print(
                f"{label}Tempo: {entry['tempo']} BPM\n"
                f"Measure: {entry['measure']}\n"
                f"Tonality: {entry['tonality']}\n"
                f"Bass estimate: {entry.get('bass_estimate')}"
            )
    
    if args.show_window:
        show_window(results)
        
    if args.output_path:
        write_json(results, args.output_path)
        print(f"Wyniki zapisano do: {args.output_path}")
        
if __name__ == "__main__":
    main()
