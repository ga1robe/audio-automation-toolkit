#!/usr/bin/env python3
"""
Audio Automation Toolkit - Unified CLI
Zarządza potokiem przetwarzania: Separacja -> Analiza -> Konwersja MIDI / ASR -> JSON Output
"""

import argparse
import json
import os
import shlex
import signal
import sys
import shutil
import subprocess
from pathlib import Path

# Definicje ścieżek środowisk wirtualnych wewnątrz kontenera
PROJECT_DIR = Path(__file__).resolve().parent.parent
"""
VENV_BASE = Path.home().joinpath('opt', 'venv311-base', 'bin', 'python3.11') if Path.home().joinpath('opt', 'venv311-base', 'bin', 'python3.11').exists() else Path("/opt/venv311-base/bin/python3.11")
VENV_TF = Path.home().joinpath('opt', 'venv311-tf', 'bin', 'python3.11') if Path.home().joinpath('opt', 'venv311-tf', 'bin', 'python3.11').exists() else Path("opt/venv311-tf/bin/python3.11")
VENV_ASR = Path.home().joinpath('opt','venv311-asr','bin','python3.11') if Path.home().joinpath('opt','venv311-asr','bin','python3.11').exists() else Path("opt/venv311-asr/bin/python3.11")
"""

VENV_BASE = Path(
    os.environ.get("VENV_BASE", "/opt/venv311-base")
) / "bin/python3.11"

VENV_TF = Path(
    os.environ.get("VENV_TF", "/opt/venv311-tf")
) / "bin/python3.11"

VENV_ASR = Path(
    os.environ.get("VENV_ASR", "/opt/venv311-asr")
) / "bin/python3.11"

def ensure_venv_interpreters(stage: str = "full") -> None:
    required = {
        "base": (VENV_BASE,),
        "tf": (VENV_TF,),
        "asr": (VENV_ASR,),
        "full": (VENV_BASE, VENV_TF, VENV_ASR),
    }

    for venv_python in required.get(stage, required["full"]):
        if not venv_python.is_file():
            raise RuntimeError(
                f"Nie znaleziono interpretera środowiska wirtualnego: {venv_python}"
            )


def log_command(stage: str, cmd: list[str], debug_stages: set[str] | None = None) -> None:
    if debug_stages is None or stage not in debug_stages:
        return
    quoted_cmd = " ".join(shlex.quote(str(part)) for part in cmd)
    print(f"[audio-toolkit][{stage}] running: {quoted_cmd}", flush=True)


def choose_recovery_stems(stems_count: int) -> int | None:
    if stems_count in {5, 4}:
        return 2
    return None


def is_kernel_kill_exit(returncode: int) -> bool:
    return returncode in (-signal.SIGKILL, signal.SIGKILL, 137, -137) or abs(returncode) == signal.SIGKILL


def run_spleeter_with_fallback(audio_path: Path, stems_dir: Path, stems_count: int, debug_steps: set[str] | None = None) -> int:
    candidate_counts = [stems_count]
    fallback = choose_recovery_stems(stems_count)
    if fallback is not None:
        candidate_counts.append(fallback)

    last_exc: subprocess.CalledProcessError | None = None
    for attempt in candidate_counts:
        cmd = [
            str(VENV_BASE.parent / "spleeter"), "separate",
            "-p", f"spleeter:{attempt}stems",
            "-o", str(stems_dir),
            str(audio_path),
        ]
        log_command("base", cmd, debug_steps)
        try:
            subprocess.run(cmd, check=True)
            return attempt
        except subprocess.CalledProcessError as exc:
            last_exc = exc
            if not is_kernel_kill_exit(exc.returncode):
                raise
            if attempt == 2:
                break
            print(
                f"[audio-toolkit][base] Spleeter was killed by the OS (likely OOM) while using {attempt} stems. Retrying with 2 stems.",
                file=sys.stderr,
                flush=True,
            )

    if last_exc is not None:
        raise RuntimeError(
            f"Spleeter was terminated by the OS while processing {audio_path}. "
            "This commonly means the Docker container is memory-constrained. "
            f"Requested stems: {stems_count}. The toolkit automatically retried with 2 stems, but the process still failed. "
            "Try a shorter audio file, reduce input length, or run the container with more RAM."
        ) from last_exc

    raise RuntimeError(f"Spleeter failed for {audio_path} without producing a valid result.")


def run_process_pipeline(
    input_dir: Path,
    output_dir: Path,
    stems_count: int = 5,
    asr_language: str = "en",
    asr_model: str = "small",
    spectro_bool: bool = False,
    debug_steps: set[str] | None = None,
    stage: str = "full",
) -> dict:
    """Uruchamia potok przetwarzania audio dla wybranego etapu lub pełnej konfiguracji."""
    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    
    """
    audio_files = [
        p for p in input_dir.iterdir() 
        if p.is_file() and p.suffix.lower() in [".wav", ".mp3", ".flac", ".m4a", ".ogg"]
    ]
    """
    
    if not input_dir.exists():
        raise FileNotFoundError(
            f"Katalog wejściowy nie istnieje: {input_dir}"
        )
    
    if not input_dir.is_dir():
        raise NotADirectoryError(
            f"Ścieżka wejściowa nie jest katalogiem: {input_dir}"
        )
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    supported_extensions = {
        ".wav", ".mp3", ".flac", ".m4a", ".ogg"
    }
    
    audio_files = sorted(
        (
            p for p in input_dir.iterdir()
            if p.is_file() and p.suffix.lower() in supported_extensions
        ),
        key=lambda p: p.name.lower()
    )
    
    if not audio_files:
        raise RuntimeError(
            f"Nie znaleziono plików audio w katalogu {input_dir}. "
            f"Znalezione elementy: {[p.name for p in input_dir.iterdir()]}"
        )
    
    execution_manifest = {
        "toolkit_version": "1.0.0",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "pipeline_stage": stage,
        "input_files": [p.name for p in audio_files],
        "processed_files_count": len(audio_files),
        "results": []
    }
    
    write_absolute_paths_bool = False
    for audio_path in audio_files:
        track_name = audio_path.stem
        track_out_dir = output_dir / track_name
        stems_dir = track_out_dir / "stems"
        midi_dir = track_out_dir / "midi"
        asr_dir = track_out_dir / "asr"
        spectro_dir = track_out_dir / "spectrograms" if spectro_bool else None
        
        track_manifest = {
            "file_name": audio_path.name,
            "original_path": str(audio_path) if write_absolute_paths_bool else os.path.relpath(audio_path, output_dir),
            "analysis": {},
            "stems": {},
            "midi": {},
            "transcription": None,
            "spectrograms": {} if spectro_bool else None
        }

        if stage in {"full", "base"}:
            # 1. Separacja Spleeter
            actual_stems_count = run_spleeter_with_fallback(audio_path, stems_dir, stems_count, debug_steps)
            stems_count = actual_stems_count

            short_actual_stems_path_bool = True
            actual_stems_path = stems_dir / track_name
            if short_actual_stems_path_bool:
                shutil.copytree(str(stems_dir / track_name),str(stems_dir), dirs_exist_ok=True)
                shutil.rmtree(str(stems_dir / track_name), ignore_errors=False)
                actual_stems_path = stems_dir / track_name
                if not actual_stems_path.exists():
                    actual_stems_path = stems_dir

            if not actual_stems_path.is_dir():
                raise RuntimeError(
                    f"Spleeter nie utworzył oczekiwanego katalogu stemów: "
                    f"{actual_stems_path}"
                )
        else:
            actual_stems_path = input_dir

        track_out_dir.mkdir(parents=True, exist_ok=True)

        if stage in {"full", "base"}:
            # 2. Analiza Audio (BPM, Key, Tonality)
            analysis_json_path = track_out_dir / "analysis.json"
            cmd_analysis = [
                str(VENV_BASE), str(PROJECT_DIR / "src/modules/analysis.py"),
                str(audio_path),
                "--output", str(analysis_json_path)
            ]
            try:
                log_command("base", cmd_analysis, debug_steps)
                subprocess.run(cmd_analysis, check=True)
            except subprocess.CalledProcessError as exc:
                print(f"Analiza zakończyła się kodem: {exc.returncode}", file=sys.stderr)
                print(f"Polecenie: {exc.cmd}", file=sys.stderr)

            if analysis_json_path.exists():
                with open(analysis_json_path, "r", encoding="utf-8") as jf:
                    track_manifest["analysis"] = json.load(jf)

            """
            determining whether 'track_manifest["analysis"]' is a list or a dictionary
            Next, check whether the ‘tempo’ parameter exists and get it to 'detected_tempo'
            """
            detected_tempo = 120.0
            analysis = track_manifest["analysis"]
            if isinstance(analysis, dict):
                detected_tempo = float(analysis.get("tempo", 120.0))
            elif isinstance(analysis, list):
                for item in analysis:
                    if isinstance(item, dict) and "tempo" in item:
                        detected_tempo = float(item["tempo"])
                        break
        else:
            detected_tempo = 120.0

        # 3. Przetwarzanie Poszczególnych Ścieżek (MIDI / ASR / Heurystyka)
        midi_dir.mkdir(parents=True, exist_ok=True)
        for stem_file in actual_stems_path.glob("*.wav"):
            stem_type = stem_file.stem.lower()
            track_manifest["stems"][stem_type] = str(stem_file) if write_absolute_paths_bool else os.path.relpath(stem_file, track_out_dir)

            if stem_type in ["vocals", "vocal"] and stage in {"full", "asr"}:
                # Whisper ASR
                cmd_asr = [
                    str(VENV_ASR), str(PROJECT_DIR / "src/modules/transcription.py"),
                    str(stem_file), str(asr_dir),
                    "--model", asr_model,
                    "--language", asr_language
                ]
                log_command("asr", cmd_asr, debug_steps)
                subprocess.run(cmd_asr, check=True)
                track_manifest["transcription"] = {
                    "txt": str(asr_dir / f"{stem_file.stem}.txt") if write_absolute_paths_bool else os.path.relpath(str(asr_dir / f"{stem_file.stem}.txt"), track_out_dir),
                    "json": str(asr_dir / f"{stem_file.stem}.json") if write_absolute_paths_bool else os.path.relpath(str(asr_dir / f"{stem_file.stem}.json"), track_out_dir),
                    "srt": str(asr_dir / f"{stem_file.stem}.srt") if write_absolute_paths_bool else os.path.relpath(str(asr_dir / f"{stem_file.stem}.srt"), track_out_dir)
                }

            if stem_type in ["vocals", "vocal"] and stage in {"full", "tf"}:
                # Basic Pitch (Melodia / Inne)
                out_midi = midi_dir / f"{stem_type}.mid"
                cmd_bp = [
                    str(VENV_TF), str(PROJECT_DIR / "src/modules/conversion_basicpitch.py"),
                    str(stem_file), str(out_midi)
                ]
                log_command("tf", cmd_bp, debug_steps)
                subprocess.run(cmd_bp, check=True)
                track_manifest["midi"][stem_type] = str(out_midi) if write_absolute_paths_bool else os.path.relpath(out_midi, track_out_dir)
            elif "drum" in stem_type and stage in {"full", "base"}:
                # Heurystyka perkusyjna
                out_midi = midi_dir / f"drums.mid"
                cmd_drums = [
                    str(VENV_BASE), str(PROJECT_DIR / "src/modules/heuristics.py"),
                    "--type", "drums", "--input", str(stem_file), "--output", str(out_midi),
                    "--tempo", str(detected_tempo)
                ]
                log_command("base", cmd_drums, debug_steps)
                subprocess.run(cmd_drums, check=True)
                track_manifest["midi"]["drums"] = str(out_midi) if write_absolute_paths_bool else os.path.relpath(out_midi, track_out_dir)
            elif "bass" in stem_type and stage in {"full", "base"}:
                # Heurystyka basowa
                out_midi = midi_dir / f"bass.mid"
                cmd_bass = [
                    str(VENV_BASE), str(PROJECT_DIR / "src/modules/heuristics.py"),
                    "--type", "bass", "--input", str(stem_file), "--output", str(out_midi),
                    "--tempo", str(detected_tempo)
                ]
                log_command("base", cmd_bass, debug_steps)
                subprocess.run(cmd_bass, check=True)
                track_manifest["midi"]["bass"] = str(out_midi) if write_absolute_paths_bool else os.path.relpath(out_midi, track_out_dir)
            elif stage in {"full", "tf"}:
                # Basic Pitch (Melodia / Inne)
                out_midi = midi_dir / f"{stem_type}.mid"
                cmd_bp = [
                    str(VENV_TF), str(PROJECT_DIR / "src/modules/conversion_basicpitch.py"),
                    str(stem_file), str(out_midi)
                ]
                log_command("tf", cmd_bp, debug_steps)
                subprocess.run(cmd_bp, check=True)
                track_manifest["midi"][stem_type] = str(out_midi) if write_absolute_paths_bool else os.path.relpath(out_midi, track_out_dir)

            if spectro_bool and stage in {"full", "base"}:
                spectro_dir.mkdir(parents=True, exist_ok=True)
                out_spectro = spectro_dir.joinpath(f"spectrogram.{stem_type}.png")
                cmd_spectro = [
                    str(VENV_BASE), str(PROJECT_DIR / "src/modules/spectrogram.py"),
                    "--input", stem_file,
                    "--output", out_spectro,
                ]
                log_command("base", cmd_spectro, debug_steps)
                subprocess.run(cmd_spectro, check=True)
                track_manifest["spectrograms"][stem_type] = str(out_spectro) if write_absolute_paths_bool else os.path.relpath(out_spectro, track_out_dir)
        execution_manifest["results"].append(track_manifest)

    return execution_manifest

def main():
    parser = argparse.ArgumentParser(
        prog="audio-toolkit",
        description="Automatyczny potok zamiany Audio do MIDI, separacji stemów i ASR."
    )
    parser.add_argument("input", type=Path, help="Katalog wejściowy z plikami audio")
    parser.add_argument("output", type=Path, help="Katalog wyjściowy na pliki MIDI, JSON, ASR")
    parser.add_argument(
        "--stage",
        choices=["base", "tf", "asr", "full"],
        default="full",
        help="Wybiera, który etap ma zostać uruchomiony: base, tf, asr lub full."
    )
    parser.add_argument("--stems", type=int, default=5, choices=[2, 4, 5], help="Liczba stemów Spleeter (domyślnie: 5)")
    parser.add_argument("--lang", type=str, default="en", help="Język transkrypcji ASR (domyślnie: en)")
    parser.add_argument("--model", type=str, default="small", help="Model Whisper (domyślnie: small)")
    parser.add_argument("--json-out", type=Path, help="Ścieżka zapisu zbiorczego raportu JSON")
    parser.add_argument('--spectro','--spectrogram',action='store_true')
    parser.add_argument(
        "--debug-steps",
        nargs="*",
        choices=["base", "tf", "asr"],
        help="Włącza logowanie komend dla wybranych etapów: base, tf, asr. Bez wartości włącza wszystkie etapy."
    )
    parser.add_argument(
        "--debug",
        action="store_const",
        const=["base", "tf", "asr"],
        dest="debug_steps",
        help="Skrót do --debug-steps base tf asr."
    )
    
    args = parser.parse_args()
    debug_steps = set(args.debug_steps) if args.debug_steps is not None else None
    if debug_steps is not None and not debug_steps:
        debug_steps = {"base", "tf", "asr"}

    ensure_venv_interpreters(stage=args.stage)

    manifest = run_process_pipeline(
        input_dir=args.input,
        output_dir=args.output,
        stems_count=args.stems,
        asr_language=args.lang,
        asr_model=args.model,
        spectro_bool=args.spectro,
        debug_steps=debug_steps,
        stage=args.stage,
    )
    
    json_output = json.dumps(manifest, ensure_ascii=False, indent=2)
    local_analysis_json_paths = [
            str(args.output.resolve() / path.stem / "analysis.json") for path in args.input.resolve().iterdir() if path.is_file() and path.suffix.lower() in [".wav", ".mp3", ".flac", ".m4a", ".ogg"]
        ]
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        if not os.path.normpath(args.json_out) in (os.path.normpath(path) for path in local_analysis_json_paths):
            with open(args.json_out, "w", encoding="utf-8") as f:
                f.write(json_output)
        else:
            actual_json_out = str(args.output.resolve() / "analysis.json")
            with open(actual_json_out, "w", encoding="utf-8") as f:
                f.write(json_output)
    else:
        json_output_path = args.output.resolve() / "manifest.json"
        with open(json_output_path, "w", encoding="utf-8") as f:
            f.write(json_output)
            
    # Standardowe wyjście JSON dla integracji z innymi systemami
    print(json_output)
    
if __name__ == "__main__":
    main()
