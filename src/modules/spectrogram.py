#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import librosa
import librosa.display

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from PIL import Image

def expand_path(value: str) -> Path:
    """
    Rozwija ~ oraz zwraca ścieżkę jako obiekt Path.
    Dzięki temu działa również wtedy, gdy użytkownik poda:
    --input '~/ścieżka/plik.wav'
    """
    return Path(value).expanduser()

def compute_log_spectrogram_db(
    wav_path: Path,
    sr: int = 22050,
    n_fft: int = 2048,
    hop_length: int = 512,
    offset_seconds: float = 0.0,
    duration_seconds: float | None = None,
) -> tuple[np.ndarray, int, float]:
    """Ładuje fragment (lub całość) WAV i zwraca (spectrum_db, loaded_sr, actual_duration_s)."""
    if not wav_path.is_file():
        raise FileNotFoundError(
            f"Nie znaleziono pliku wejściowego: {wav_path}"
        )

    y, loaded_sr = librosa.load(
        str(wav_path),
        sr=sr,
        mono=True,
        offset=max(0.0, float(offset_seconds)),
        duration=duration_seconds,
    )

    if y.size == 0:
        raise ValueError(f"Plik audio jest pusty: {wav_path}")

    spectrum = librosa.stft(
        y,
        n_fft=n_fft,
        hop_length=hop_length,
    )
    amplitude = np.abs(spectrum)
    spectrum_db = librosa.amplitude_to_db(
        amplitude,
        ref=np.max,
    )
    actual_duration_s = float(y.shape[0]) / float(loaded_sr)
    return spectrum_db, loaded_sr, actual_duration_s

def save_spectrogram(
    wav_path: Path,
    img_path: Path,
    sr: int = 22050,
    n_fft: int = 2048,
    hop_length: int = 512,
    offset_seconds: float = 0.0,
    duration_seconds: float | None = None,
    bare_panel: bool = False,
    title: str | None = None,
) -> None:
    """
    Tworzy i zapisuje spectrogram pliku WAV (lub jego wycinka czasowego).
    """
    spectrum_db, loaded_sr, actual_duration_s = compute_log_spectrogram_db(
        wav_path=wav_path,
        sr=sr,
        n_fft=n_fft,
        hop_length=hop_length,
        offset_seconds=offset_seconds,
        duration_seconds=duration_seconds,
    )

    stem_name = wav_path.stem
    plot_title = title if title is not None else f"Spectrogram: {stem_name}"
    start_time_s = max(0.0, float(offset_seconds))
    n_frames = spectrum_db.shape[1]
    x_coords = (
        np.linspace(start_time_s, start_time_s + actual_duration_s, n_frames)
        if n_frames > 0
        else None
    )

    img_path.parent.mkdir(parents=True, exist_ok=True)

    if bare_panel:
        fig, ax = plt.subplots(figsize=(10, 4))
        librosa.display.specshow(
            spectrum_db,
            sr=loaded_sr,
            hop_length=hop_length,
            x_axis="time",
            x_coords=x_coords,
            y_axis="log",
            cmap="magma",
            shading="nearest",
            ax=ax,
        )
        ax.set_axis_off()
        fig.savefig(
            str(img_path),
            dpi=150,
            bbox_inches="tight",
            pad_inches=0,
        )
        plt.close(fig)
        return

    fig, ax = plt.subplots(figsize=(10, 4))
    image = librosa.display.specshow(
        spectrum_db,
        sr=loaded_sr,
        hop_length=hop_length,
        x_axis="time",
        x_coords=x_coords,
        y_axis="log",
        cmap="magma",
        shading="nearest",
        ax=ax,
    )
    fig.colorbar(
        image,
        ax=ax,
        format="%+2.0f dB",
    )
    ax.set_title(plot_title)
    fig.tight_layout()
    fig.savefig(
        str(img_path),
        dpi=150,
        bbox_inches="tight",
    )
    plt.close(fig)

def combine_spectrogram_tiles_horizontal(
    tile_paths: list[Path],
    output_path: Path,
) -> None:
    """Łączy wygenerowane kafelki PNG w poziomie oszczędnie pamięciowo."""
    if not tile_paths:
        raise ValueError("Brak kafelków spektrogramu do połączenia.")

    images = [Image.open(path) for path in tile_paths]
    try:
        target_height = min(img.height for img in images)
        resized: list[Image.Image] = []
        for img in images:
            rgb_img = img.convert("RGB")
            if rgb_img.height != target_height:
                new_width = max(
                    1, int(round(rgb_img.width * target_height / rgb_img.height))
                )
                rgb_img = rgb_img.resize(
                    (new_width, target_height), Image.Resampling.BILINEAR
                )
            resized.append(rgb_img)

        total_width = sum(img.width for img in resized)
        combined = Image.new("RGB", (total_width, target_height))
        cursor_x = 0
        for img in resized:
            combined.paste(img, (cursor_x, 0))
            cursor_x += img.width
            img.close()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        combined.save(str(output_path), format="PNG")
        combined.close()
    finally:
        for img in images:
            img.close()

def render_combined_full_axis_spectrogram(
    wav_path: Path,
    chunk_specs_json: Path,
    img_path: Path,
    sr: int = 22050,
    n_fft: int = 2048,
    hop_length: int = 512,
) -> None:
    """
    Przelicza pełną oś czasu dla segmentów (offset_seconds, duration_seconds)
    i rysuje jeden wspólny spektrogram z pełną skalą czasu.
    """
    chunk_specs = json.loads(chunk_specs_json.read_text(encoding="utf-8"))
    if not chunk_specs:
        raise ValueError("Lista segmentów spektrogramu jest pusta.")

    segments_db: list[np.ndarray] = []
    time_segments: list[np.ndarray] = []
    loaded_sr = sr

    for spec in chunk_specs:
        offset_s = float(spec["offset_seconds"])
        duration_s = float(spec["duration_seconds"])
        spectrum_db, loaded_sr, actual_dur_s = compute_log_spectrogram_db(
            wav_path=wav_path,
            sr=sr,
            n_fft=n_fft,
            hop_length=hop_length,
            offset_seconds=offset_s,
            duration_seconds=duration_s,
        )
        n_frames = spectrum_db.shape[1]
        if n_frames > 0:
            # Środki ramek w rzeczywistej osi czasu całego nagrania
            frame_times = offset_s + (
                np.arange(n_frames, dtype=float) * hop_length / float(loaded_sr)
            )
            # Przytnij do deklarowanego okna, jeśli występują lekkie zaokrąglenia
            mask = frame_times <= (offset_s + actual_dur_s + 1e-6)
            segments_db.append(spectrum_db[:, mask].astype(np.float32, copy=False))
            time_segments.append(frame_times[mask])

    if not segments_db:
        raise ValueError("Nie udało się wygenerować żadnego segmentu spektrogramu.")

    full_spectrum_db = np.concatenate(segments_db, axis=1).astype(
        np.float32, copy=False
    )
    full_times = np.concatenate(time_segments, axis=0)

    # Budujemy krawędzie komórek dla pełnej przeliczonej osi czasu
    if full_times.size == 1:
        dt = hop_length / float(loaded_sr)
        x_edges = np.array([full_times[0], full_times[0] + dt], dtype=float)
    else:
        midpoints = 0.5 * (full_times[:-1] + full_times[1:])
        first_edge = max(0.0, full_times[0] - (midpoints[0] - full_times[0]))
        last_edge = full_times[-1] + (full_times[-1] - midpoints[-1])
        x_edges = np.concatenate(([first_edge], midpoints, [last_edge]))

    stem_name = wav_path.stem
    img_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(12, 4))
    image = librosa.display.specshow(
        full_spectrum_db,
        sr=loaded_sr,
        hop_length=hop_length,
        x_axis="time",
        x_coords=full_times,
        y_axis="log",
        cmap="magma",
        shading="nearest",
        ax=ax,
    )
    fig.colorbar(
        image,
        ax=ax,
        format="%+2.0f dB",
    )
    ax.set_xlim(float(x_edges[0]), float(x_edges[-1]))
    ax.set_title(f"Spectrogram: {stem_name}")
    fig.tight_layout()
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

    parser.add_argument(
        "--offset-seconds",
        type=float,
        default=0.0,
        help="Przesunięcie początkowe w sekundach (dla fragmentów).",
    )

    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=None,
        help="Długość fragmentu w sekundach.",
    )

    parser.add_argument(
        "--bare-panel",
        action="store_true",
        help="Renderuje sam panel spektrogramu bez osi, tytułu i paska kolorów.",
    )

    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help="Opcjonalny tytuł wykresu.",
    )

    parser.add_argument(
        "--stitch-tiles",
        nargs="+",
        type=expand_path,
        default=None,
        help="Łączy wskazane pliki PNG w poziomie do --output.",
    )

    parser.add_argument(
        "--combine-full-axis-from-chunks",
        type=expand_path,
        default=None,
        help="Ścieżka do JSON z definicją chunków do scalenia na pełnej osi czasu.",
    )

    args = parser.parse_args()

    if args.sr <= 0:
        parser.error("--sr musi być większe od zera.")

    if args.n_fft <= 0:
        parser.error("--n-fft musi być większe od zera.")

    if args.hop_length <= 0:
        parser.error("--hop-length musi być większe od zera.")

    if args.offset_seconds < 0:
        parser.error("--offset-seconds nie może być ujemne.")

    if args.duration_seconds is not None and args.duration_seconds <= 0:
        parser.error("--duration-seconds musi być większe od zera.")

    if args.output.suffix.lower() != ".png":
        parser.error("--output powinien wskazywać plik z rozszerzeniem .png.")

    return args

def main() -> int:
    args = parse_args()

    try:
        if args.stitch_tiles:
            combine_spectrogram_tiles_horizontal(
                tile_paths=args.stitch_tiles,
                output_path=args.output,
            )
        elif args.combine_full_axis_from_chunks:
            render_combined_full_axis_spectrogram(
                wav_path=args.input,
                chunk_specs_json=args.combine_full_axis_from_chunks,
                img_path=args.output,
                sr=args.sr,
                n_fft=args.n_fft,
                hop_length=args.hop_length,
            )
        else:
            save_spectrogram(
                wav_path=args.input,
                img_path=args.output,
                sr=args.sr,
                n_fft=args.n_fft,
                hop_length=args.hop_length,
                offset_seconds=args.offset_seconds,
                duration_seconds=args.duration_seconds,
                bare_panel=args.bare_panel,
                title=args.title,
            )
    except Exception as error:
        print(f"Błąd: {error}", file=sys.stderr)
        return 1

    print(f"[info] Spectrogram zapisano w: {args.output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
