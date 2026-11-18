#!/usr/bin/env python3
import sys
import json
import argparse
import numpy as np
import librosa
import librosa.display
#import tkinter as tk
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib.pyplot as plt

from splitter import split_dj_set_by_silence


def _analyze_audio_file(
    file_path: str,
    spectrogram_path: str | None = None,
) -> dict:
    """Wczytuje plik audio i zwraca podstawowe metadane oraz zapisuje spektrogram."""
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
    
    # SPECTROGRAM: zapisz log-mel spectrogram i standardowy spektrogram
    spec_info = None
    if spectrogram_path:
        spectrogram_png = Path(spectrogram_path)
        spectrogram_png.parent.mkdir(parents=True, exist_ok=True)
        spec_info = str(spectrogram_png)
        
    # BASS ESTIMATE: prosty oszacowanie linii basu przez librosa.pyin (fokus niskie freq)
    bass_estimate = None
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
        #"spectrogram_png": spec_info,
        "bass_estimate": bass_estimate
    }


def analyze_audio(
    file_path: str,
    spectrogram_path: str | None = None,
) -> dict | list[dict]:
    """Analyze silence-separated, duration-capped chunks of the source audio."""
    source_path = Path(file_path)
    with TemporaryDirectory(prefix="audio-analysis-") as temp_dir:
        chunk_paths = split_dj_set_by_silence(source_path, Path(temp_dir))
        analyses: list[dict] = []

        for index, chunk_path in enumerate(chunk_paths, start=1):
            chunk_spectrogram_path = None
            if spectrogram_path:
                output_path = Path(spectrogram_path)
                chunk_spectrogram_path = str(
                    output_path.with_name(
                        f"{output_path.stem}.segment_{index:02d}{output_path.suffix}"
                    )
                    if len(chunk_paths) > 1
                    else output_path
                )

            result = _analyze_audio_file(
                str(chunk_path),
                chunk_spectrogram_path,
            )
            result["file"] = source_path.name
            if len(chunk_paths) > 1:
                result["segment"] = chunk_path.name
            analyses.append(result)

    return analyses[0] if len(analyses) == 1 else analyses
    
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
        "--spectrogram",
        dest="spectrogram",
        metavar="PNG",
        help="Ścieżka do pliku PNG, w którym zostanie zapisany spektrogram (Mel).",
    )
    return parser
    
def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    
    if not args.audio_file:
        parser.print_help()
        sys.exit(0)
        
    # jeśli nie podano ścieżki spektrogramu, zapisz obok pliku wynikowego JSON (jeśli podany)
    spectrogram_path = None
    if args.spectrogram:
        spectrogram_path = args.spectrogram
    elif args.output_path:
        outp = Path(args.output_path)
        spectrogram_path = str(outp.with_suffix(".spectrogram.png"))
    
    results = analyze_audio(args.audio_file, spectrogram_path)
    
    if args.show_cli:
        entries = results if isinstance(results, list) else [results]
        for index, entry in enumerate(entries, start=1):
            label = f"Segment {index}: " if len(entries) > 1 else ""
            print(
                f"{label}Tempo: {entry['tempo']} BPM\n"
                f"Measure: {entry['measure']}\n"
                f"Tonality: {entry['tonality']}\n"
                f"Spectrogram: {entry.get('spectrogram_png')}\n"
                f"Bass estimate: {entry.get('bass_estimate')}"
            )
    
    if args.show_window:
        show_window(results)
        
    if args.output_path:
        write_json(results, args.output_path)
        print(f"Wyniki zapisano do: {args.output_path}")
        
if __name__ == "__main__":
    main()
