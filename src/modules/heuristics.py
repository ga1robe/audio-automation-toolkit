#!/usr/bin/env python3

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import librosa
import numpy as np
import pretty_midi

DRUM_MAP = {
    "kick": 36,
    "snare": 38,
    "closed_hat": 42,
    "open_hat": 46,
    "tom_low": 45,
    "crash": 49,
}

def quantize_time(
    time_sec: float,
    tempo_bpm: float,
    quant: int = 16,
) -> float:
    """
    Kwantyzacja do siatki szesnastkowej przy zadanym tempie.

    quant=4  -> ćwierćnuty
    quant=8  -> ósemki
    quant=16 -> szesnastki
    """
    if tempo_bpm <= 0:
        return time_sec
        
    beat_sec = 60.0 / tempo_bpm
    grid_sec = beat_sec * 4.0 / quant
    
    return round(time_sec / grid_sec) * grid_sec
    
def clamp_midi(value: float) -> int:
    return max(1, min(127, int(round(value))))
    
def classify_drum_window(
    window: np.ndarray,
    sample_rate: int,
    hop_length: int,
) -> tuple[str, int]:
    """
    Prosta klasyfikacja pojedynczego onsetu na kick/snare/hat.
    """
    if window.size == 0:
        return "snare", 80
        
    if np.max(np.abs(window)) > 0:
        window = window / np.max(np.abs(window))
        
    energy = float(np.mean(window ** 2))
    
    # Krótkie okna mogą być zbyt małe dla STFT.
    n_fft = min(1024, max(256, 2 ** int(np.ceil(np.log2(len(window))))))
    if n_fft > len(window):
        window = np.pad(window, (0, n_fft - len(window)))
        
    spectrum = np.abs(
        librosa.stft(
            window,
            n_fft=n_fft,
            hop_length=min(hop_length, n_fft // 4),
            center=False,
        )
    )
    
    if spectrum.size == 0:
        return "snare", 80
    
    freqs = librosa.fft_frequencies(sr=sample_rate, n_fft=n_fft)
    
    low_mask = freqs < 180
    mid_mask = (freqs >= 180) & (freqs < 2200)
    high_mask = freqs >= 2200
    
    low_energy = float(spectrum[low_mask].sum())
    mid_energy = float(spectrum[mid_mask].sum())
    high_energy = float(spectrum[high_mask].sum())
    
    centroid = float(
        librosa.feature.spectral_centroid(
            y=window,
            sr=sample_rate,
            n_fft=n_fft,
            hop_length=min(hop_length, n_fft // 4),
        ).mean()
    )
    
    # Kick: dominująca energia niskich częstotliwości.
    if (
        low_energy > 0
        and low_energy > (mid_energy + high_energy) * 0.75
        and centroid < 1400
    ):
        velocity = clamp_midi(45 + energy * 9000)
        return "kick", velocity
        
    # Hi-hat: dużo energii wysokich częstotliwości.
    if (
        high_energy > 0
        and high_energy > (low_energy + mid_energy) * 0.55
        and centroid > 2800
    ):
        velocity = clamp_midi(30 + energy * 7000)
        return "closed_hat", velocity
        
    # Snare albo element środka pasma.
    velocity = clamp_midi(45 + energy * 10000)
    return "snare", velocity
    
def drums_to_midi(
    input_wav: Path,
    output_midi: Path,
    tempo_bpm: float,
    sample_rate: int = 44100,
    hop_length: int = 512,
    quant: int = 16,
) -> Path:
    y, sr = librosa.load(
        str(input_wav),
        sr=sample_rate,
        mono=True,
    )
    
    if y.size == 0:
        raise RuntimeError(f"Pusty plik audio: {input_wav}")
    
    onset_frames = librosa.onset.onset_detect(
        y=y,
        sr=sr,
        hop_length=hop_length,
        backtrack=True,
        units="frames",
    )
    
    onset_times = librosa.frames_to_time(
        onset_frames,
        sr=sr,
        hop_length=hop_length,
    )
    
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo_bpm)
    
    # is_drum=True powoduje zapis na kanale perkusyjnym MIDI.
    drum_track = pretty_midi.Instrument(
        program=0,
        is_drum=True,
        name="Drums",
    )
    
    window_length = int(0.12 * sr)
    
    for onset_time in onset_times:
        start_sample = max(0, int(onset_time * sr))
        end_sample = min(len(y), start_sample + window_length)
        
        window = y[start_sample:end_sample]
        drum_name, velocity = classify_drum_window(
            window,
            sample_rate=sr,
            hop_length=hop_length,
        )
        
        pitch = DRUM_MAP[drum_name]
        
        start_time = quantize_time(
            float(onset_time),
            tempo_bpm,
            quant=quant,
        )
        
        # Zapobiega ujemnemu czasowi po kwantyzacji.
        start_time = max(0.0, start_time)
        end_time = start_time + 0.06
        
        drum_track.notes.append(
            pretty_midi.Note(
                velocity=velocity,
                pitch=pitch,
                start=start_time,
                end=end_time,
            )
        )
        
    midi.instruments.append(drum_track)
    
    output_midi.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(output_midi))
    
    return output_midi
    
def append_note(
    instrument: pretty_midi.Instrument,
    midi_pitch: int,
    start_time: float,
    end_time: float,
    velocity: int,
    tempo_bpm: float,
    quant: int,
    quantize: bool,
) -> None:
    if end_time <= start_time:
        return
        
    # Usuwamy bardzo krótkie, przypadkowe detekcje.
    if end_time - start_time < 0.08:
        return
    
    if quantize:
        start_time = quantize_time(start_time, tempo_bpm, quant)
        end_time = quantize_time(end_time, tempo_bpm, quant)
        
    start_time = max(0.0, start_time)
    end_time = max(start_time + 0.04, end_time)
    
    instrument.notes.append(
        pretty_midi.Note(
            velocity=clamp_midi(velocity),
            pitch=max(0, min(127, int(midi_pitch))),
            start=start_time,
            end=end_time,
        )
    )
    
def bass_to_midi(
    input_wav: Path,
    output_midi: Path,
    tempo_bpm: float,
    sample_rate: int = 22050,
    fmin: float = 40.0,
    fmax: float = 300.0,
    hop_length: int = 256,
    quant: int = 16,
    quantize: bool = True,
) -> Path:
    y, sr = librosa.load(
        str(input_wav),
        sr=sample_rate,
        mono=True,
    )
    
    if y.size == 0:
        raise RuntimeError(f"Pusty plik audio: {input_wav}")
    
    try:
        pitches, voiced_flags, voiced_probabilities = librosa.pyin(
            y,
            fmin=fmin,
            fmax=fmax,
            sr=sr,
            hop_length=hop_length,
            fill_na=np.nan,
        )
    except Exception as exc:
        raise RuntimeError(
            "Nie udało się wykonać detekcji basu przez librosa.pyin"
        ) from exc
        
    times = librosa.frames_to_time(
        np.arange(len(pitches)),
        sr=sr,
        hop_length=hop_length,
    )
    
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo_bpm)
    
    # Program 32 w pretty_midi to 0-based Acoustic Bass.
    bass_track = pretty_midi.Instrument(
        program=32,
        is_drum=False,
        name="Bass",
    )
    
    current_pitch: int | None = None
    current_start: float | None = None
    
    def close_current(end_time: float) -> None:
        nonlocal current_pitch, current_start
        
        if current_pitch is not None and current_start is not None:
            append_note(
                instrument=bass_track,
                midi_pitch=current_pitch,
                start_time=current_start,
                end_time=end_time,
                velocity=84,
                tempo_bpm=tempo_bpm,
                quant=quant,
                quantize=quantize,
            )
            
        current_pitch = None
        current_start = None
        
    for pitch_hz, voiced, time_sec in zip(
        pitches,
        voiced_flags,
        times,
    ):
        valid_pitch = (
            voiced
            and pitch_hz is not None
            and np.isfinite(pitch_hz)
            and pitch_hz > 0
        )
        
        if not valid_pitch:
            close_current(float(time_sec))
            continue
            
        midi_pitch = int(round(float(librosa.hz_to_midi(pitch_hz))))
        midi_pitch = max(0, min(127, midi_pitch))
        
        if current_pitch is None:
            current_pitch = midi_pitch
            current_start = float(time_sec)
            continue
            
        # Zmiana o co najmniej pół tonu kończy poprzednią nutę.
        if abs(current_pitch - midi_pitch) >= 1:
            close_current(float(time_sec))
            current_pitch = midi_pitch
            current_start = float(time_sec)
            
    if len(times) > 0:
        final_time = float(times[-1]) + hop_length / sr
    else:
        final_time = 0.1
        
    close_current(final_time)
    
    midi.instruments.append(bass_track)
    
    output_midi.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(output_midi))
    
    return output_midi
    
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Heurystyczna konwersja stemów drums/bass do MIDI."
    )
    
    parser.add_argument(
        "--type",
        required=True,
        choices=("drums", "bass"),
        help="Typ przetwarzanego stema.",
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Wejściowy plik WAV.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Wyjściowy plik MIDI.",
    )
    parser.add_argument(
        "--tempo",
        type=float,
        default=120.0,
        help="Tempo BPM, domyślnie 120.",
    )
    parser.add_argument(
        "--no-quantize",
        action="store_true",
        help="Nie kwantyzuj nut/onsetów.",
    )
    
    return parser.parse_args()
    
def main() -> int:
    args = parse_args()
    
    if not args.input.exists():
        print(f"Brak pliku wejściowego: {args.input}", file=sys.stderr)
        return 2
    
    if args.tempo <= 0:
        print("Tempo musi być większe od zera.", file=sys.stderr)
        return 2
    
    try:
        if args.type == "drums":
            result = drums_to_midi(
                input_wav=args.input,
                output_midi=args.output,
                tempo_bpm=args.tempo,
            )
        else:
            result = bass_to_midi(
                input_wav=args.input,
                output_midi=args.output,
                tempo_bpm=args.tempo,
                quantize=not args.no_quantize,
            )
        
        print(f"[info] zapisano MIDI: {result}")
        return 0
        
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
        
if __name__ == "__main__":
    raise SystemExit(main())
