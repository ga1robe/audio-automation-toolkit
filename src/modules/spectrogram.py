#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

import numpy as np
import librosa
import librosa.display

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

def expand_path(value: str) -> Path:
    """
    Rozwija ~ oraz zwraca ścieżkę jako obiekt Path.
    Dzięki temu działa również wtedy, gdy użytkownik poda:
    --input '~/ścieżka/plik.wav'
    """
    return Path(value).expanduser()
    
def save_spectrogram(
    wav_path: Path,
    img_path: Path,
    sr: int = 22050,
    n_fft: int = 2048,
    hop_length: int = 512,
) -> None:
    """
    Tworzy i zapisuje spectrogram pliku WAV.
    Nazwa stemu jest pobierana z nazwy pliku wejściowego.
    Przykład:
        other.wav -> stem_name = "other"
    """
    
    if not wav_path.is_file():
        raise FileNotFoundError(
            f"Nie znaleziono pliku wejściowego: {wav_path}"
        )
        
    # Nazwa stemu bez rozszerzenia, np. "other.wav" -> "other"
    stem_name = wav_path.stem
    
    # Wczytanie pliku audio
    y, loaded_sr = librosa.load(
        str(wav_path),
        sr=sr,
        mono=True,
    )
    
    if y.size == 0:
        raise ValueError(f"Plik audio jest pusty: {wav_path}")
        
    # Transformata STFT
    spectrum = librosa.stft(
        y,
        n_fft=n_fft,
        hop_length=hop_length,
    )
    
    amplitude = np.abs(spectrum)
    
    # Konwersja amplitudy do decybeli
    spectrum_db = librosa.amplitude_to_db(
        amplitude,
        ref=np.max,
    )
    
    # Utworzenie katalogu wyjściowego
    img_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Rysowanie spectrogramu
    fig, ax = plt.subplots(figsize=(10, 4))
    
    image = librosa.display.specshow(
        spectrum_db,
        sr=loaded_sr,
        hop_length=hop_length,
        x_axis="time",
        y_axis="log",
        cmap="magma",
        ax=ax,
    )
    
    fig.colorbar(
        image,
        ax=ax,
        format="%+2.0f dB",
    )
    
    ax.set_title(f"Spectrogram: {stem_name}")
    fig.tight_layout()
    
    # Zapis obrazu
    fig.savefig(
        str(img_path),
        dpi=150,
        bbox_inches="tight",
    )
    
    plt.close(fig)
    
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tworzenie spectrogramu na podstawie pliku WAV."
    )
    
    parser.add_argument(
        "--input",
        required=True,
        type=expand_path,
        metavar="PLIK_WAV",
        help="Ścieżka do wejściowego pliku WAV.",
    )
    
    parser.add_argument(
        "--output",
        required=True,
        type=expand_path,
        metavar="PLIK_PNG",
        help="Ścieżka do wyjściowego pliku PNG.",
    )
    
    parser.add_argument(
        "--sr",
        type=int,
        default=22050,
        help="Częstotliwość próbkowania, domyślnie: 22050.",
    )
    
    parser.add_argument(
        "--n-fft",
        type=int,
        default=2048,
        dest="n_fft",
        help="Rozmiar FFT, domyślnie: 2048.",
    )
    
    parser.add_argument(
        "--hop-length",
        type=int,
        default=512,
        dest="hop_length",
        help="Odległość pomiędzy kolejnymi ramkami, domyślnie: 512.",
    )
    
    args = parser.parse_args()
    
    if args.sr <= 0:
        parser.error("--sr musi być większe od zera.")
        
    if args.n_fft <= 0:
        parser.error("--n-fft musi być większe od zera.")
        
    if args.hop_length <= 0:
        parser.error("--hop-length musi być większe od zera.")
        
    if args.output.suffix.lower() != ".png":
        parser.error("--output powinien wskazywać plik z rozszerzeniem .png.")
        
    return args
    
def main() -> int:
    args = parse_args()
    
    try:
        save_spectrogram(
            wav_path=args.input,
            img_path=args.output,
            sr=args.sr,
            n_fft=args.n_fft,
            hop_length=args.hop_length,
        )
    except Exception as error:
        print(f"Błąd: {error}", file=sys.stderr)
        return 1
        
    print(f"[info] Spectrogram zapisano w: {args.output}")
    return 0
    
if __name__ == "__main__":
    raise SystemExit(main())
