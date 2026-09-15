#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

# Basic Pitch imports (lazy)
try:
    from basic_pitch.inference import predict_and_save
    from basic_pitch import ICASSP_2022_MODEL_PATH
    BASIC_PITCH_AVAILABLE = True
    predict = None
except Exception as e:
    traceback.print_exc()
    predict_and_save = None
    ICASSP_2022_MODEL_PATH = None
    BASIC_PITCH_AVAILABLE = False
    try:
        from basic_pitch.inference import predict
        from basic_pitch import ICASSP_2022_MODEL_PATH
        BASIC_PITCH_AVAILABLE = True
    except Exception as e:
        import traceback
        traceback.print_exc()
        predict = None
        ICASSP_2022_MODEL_PATH = None
        BASIC_PITCH_AVAILABLE = False
        
def convert_audio_to_midi(
    input_wav: Path,
    output_midi: Path,
) -> Path:
    """
    try:
        from basic_pitch.inference import predict_and_save
        from basic_pitch import ICASSP_2022_MODEL_PATH
    except ImportError as exc:
        raise RuntimeError(
            "Brak biblioteki basic-pitch. Zainstaluj ją w środowisku VENV_TF."
        ) from exc
    """
        
    output_midi.parent.mkdir(parents=True, exist_ok=True)
    
    with tempfile.TemporaryDirectory(
        prefix="basic_pitch_"
    ) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        if predict_and_save is not None:
            predict_and_save(
                [str(input_wav)],
                str(temp_dir),
                save_midi=True,
                sonify_midi=False,
                save_model_outputs=False,
                save_notes=False,
                model_or_model_path=ICASSP_2022_MODEL_PATH,
            )
        elif predict is not None:
            _, midi_data, _ = predict(
                str(input_wav),
                ICASSP_2022_MODEL_PATH,
            )
            midi_data.write(str(output_midi))
            print(f"MIDI saved to {output_midi}")
            
        midi_files = sorted(temp_dir.glob("*.mid"))
        
        if not midi_files:
            midi_files = sorted(temp_dir.glob("*.midi"))
            
        if not midi_files:
            raise RuntimeError(
                f"Basic Pitch nie wygenerował pliku MIDI dla: {input_wav}"
            )
            
        # Zwykle powstaje jeden plik. W przypadku kilku wybieramy ten
        # odpowiadający nazwie wejściowego WAV.
        expected_stem = input_wav.stem.lower()
        
        matching_files = [
            path
            for path in midi_files
            if expected_stem in path.stem.lower()
        ]
        
        source_midi = matching_files[0] if matching_files else midi_files[0]
        
        shutil.copy2(source_midi, output_midi)
        
    return output_midi
    
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Konwersja pliku audio do MIDI przez Basic Pitch."
    )
    
    parser.add_argument(
        "input_wav",
        type=Path,
        help="Wejściowy plik WAV/audio.",
    )
    parser.add_argument(
        "output_midi",
        type=Path,
        help="Docelowy plik MIDI.",
    )
    
    return parser.parse_args()
    
def main() -> int:
    args = parse_args()

    if not args.input_wav.exists():
        print(
            f"Brak pliku wejściowego: {args.input_wav}",
            file=sys.stderr,
        )
        return 2
        
    try:
        result = convert_audio_to_midi(
            input_wav=args.input_wav,
            output_midi=args.output_midi,
        )
        
        print(f"[info] Basic Pitch zapisał MIDI: {result}")
        return 0
        
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
        
if __name__ == "__main__":
    raise SystemExit(main())
