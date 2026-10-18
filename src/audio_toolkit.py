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
import tempfile
import wave
from pathlib import Path

# Definicje ścieżek środowisk wirtualnych wewnątrz kontenera
PROJECT_DIR = Path(__file__).resolve().parent.parent
SPLEETER_CHUNK_DURATION_MS = 5 * 60 * 1000
SPLEETER_CHUNK_TIMEOUT_SECONDS = int(
    os.environ.get("SPLEETER_CHUNK_TIMEOUT_SECONDS", "900")
)
DEMUCS_STEM_NAMES = {
    2: {"vocals.wav", "accompaniment.wav"},
    4: {"vocals.wav", "drums.wav", "bass.wav", "other.wav"},
    6: {"vocals.wav", "drums.wav", "bass.wav", "other.wav", "guitar.wav", "piano.wav"},
}
"""
SPLEETER_STEM_NAMES = {
    2: {"vocals.wav", "accompaniment.wav"},
    4: {"vocals.wav", "drums.wav", "bass.wav", "other.wav"},
    5: {"vocals.wav", "drums.wav", "bass.wav", "piano.wav", "other.wav"},
}
"""
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

def ensure_venv_interpreters(stage: str = "full", skip_asr: bool = False) -> None:
    required = {
        "base": (VENV_BASE,),
        "tf": (VENV_TF,),
        "asr": (VENV_ASR,),
        "full": (VENV_BASE, VENV_TF, VENV_ASR),
    }

    interpreters = required.get(stage, required["full"])
    if skip_asr:
        interpreters = tuple(python for python in interpreters if python != VENV_ASR)

    for venv_python in interpreters:
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


def normalize_asr_language(language: str | None) -> str | None:
    if language is None:
        return None

    normalized = str(language).strip().lower().replace("_", "-")
    if not normalized or normalized in {"none", "auto"}:
        return None

    locale = normalized.split("-", 1)[0]
    aliases = {
        "us": "en",
        "usa": "en",
        "en": "en",
        "english": "en",
        "gb": "en",
        "uk": "en",
        "ca": "en",
        "au": "en",
    }
    return aliases.get(locale, normalized)


def is_kernel_kill_exit(returncode: int) -> bool:
    return returncode in (-signal.SIGKILL, signal.SIGKILL, 137, -137) or abs(returncode) == signal.SIGKILL


def split_audio_into_chunks(audio_path: Path, chunks_dir: Path) -> list[Path]:
    from pydub import AudioSegment

    chunks_dir.mkdir(parents=True, exist_ok=True)
    chunks = []
    start_ms = 0

    while True:
        segment = AudioSegment.from_file(
            str(audio_path),
            start_second=start_ms / 1000,
            duration=SPLEETER_CHUNK_DURATION_MS / 1000,
        )
        segment_duration_ms = len(segment)
        if segment_duration_ms == 0:
            break

        chunk_path = chunks_dir / f"chunk_{len(chunks):06d}.wav"
        segment.export(chunk_path, format="wav")
        del segment
        chunks.append(chunk_path)

        if segment_duration_ms < SPLEETER_CHUNK_DURATION_MS:
            break
        start_ms += SPLEETER_CHUNK_DURATION_MS

    if not chunks:
        raise RuntimeError(f"Nie udało się odczytać audio z pliku: {audio_path}")

    return chunks


def combine_spleeter_stems(
    chunk_stem_paths: list[Path],
    output_path: Path,
) -> None:
    with wave.open(str(chunk_stem_paths[0]), "rb") as first_chunk:
        first_params = first_chunk.getparams()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with wave.open(str(output_path), "wb") as combined:
            combined.setparams(first_params)
            for chunk_stem_path in chunk_stem_paths:
                with wave.open(str(chunk_stem_path), "rb") as chunk:
                    params = chunk.getparams()
                    if (
                        params.nchannels != first_params.nchannels
                        or params.sampwidth != first_params.sampwidth
                        or params.framerate != first_params.framerate
                        or params.comptype != first_params.comptype
                        or params.compname != first_params.compname
                    ):
                        raise RuntimeError(
                            f"Niezgodny format ścieżki Spleeter: {chunk_stem_path}"
                        )

                    while frames := chunk.readframes(65536):
                        combined.writeframesraw(frames)


def run_demucs_with_fallback(audio_path: Path, stems_dir: Path, stems_count: int, debug_steps: set[str] | None = None) -> int:
    # Wybieramy odpowiedni model Demucs w zależności od żądanej liczby stemów
    if stems_count >= 6:
        model_name = "htdemucs_6s"
        candidate_counts = [6, 4] # Fallback do 4 stemów w razie OOM
    elif stems_count >= 4:
        model_name = "htdemucs"
        candidate_counts = [4, 2]
    else:
        model_name = "htdemucs"
        candidate_counts = [2]

    last_exc: subprocess.CalledProcessError | subprocess.TimeoutExpired | None = None
    stems_dir.mkdir(parents=True, exist_ok=True)
    track_name = audio_path.stem

    with tempfile.TemporaryDirectory(
        prefix="demucs_chunks_",
        dir=stems_dir,
    ) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        chunk_paths = split_audio_into_chunks(audio_path, temp_dir / "chunks")

        for attempt_stems in candidate_counts:
            active_model = "htdemucs_6s" if attempt_stems >= 6 else "htdemucs"
            attempt_dir = temp_dir / f"separated_{attempt_stems}stems"
            attempt_dir.mkdir(exist_ok=True)
            try:
                for chunk_index, chunk_path in enumerate(chunk_paths, start=1):
                    print(
                        f"[audio-toolkit][base] Separating chunk {chunk_index}/{len(chunk_paths)} "
                        f"using Demucs model '{active_model}' ({attempt_stems} stems).",
                        flush=True,
                    )
                    # Wywołanie Demucs jako modułu Pythona w środowisku base
                    cmd = [
                        str(VENV_BASE), "-m", "demucs.separate",
                        "-n", active_model,
                        "-o", str(attempt_dir),
                        str(chunk_path),
                    ]
                    log_command("base", cmd, debug_steps)
                    subprocess.run(
                        cmd,
                        check=True,
                        timeout=SPLEETER_CHUNK_TIMEOUT_SECONDS,
                    )

                # Demucs tworzy strukturę: attempt_dir / model_name / chunk_stem / stem_files.wav
                chunk_output_dirs = [
                    attempt_dir / active_model / chunk_path.stem
                    for chunk_path in chunk_paths
                ]
                
                stem_names = sorted(
                    path.name for path in chunk_output_dirs[0].glob("*.wav")
                )
                expected_stems = DEMUCS_STEM_NAMES.get(attempt_stems, DEMUCS_STEM_NAMES[4])
                
                # Walidacja wygenerowanych stemów
                if not expected_stems.issubset(set(stem_names)):
                    raise RuntimeError(
                        f"Demucs produced unexpected stems for {audio_path}: "
                        f"{stem_names}; expected at least {sorted(expected_stems)}"
                    )

                assembled_dir = temp_dir / f"assembled_{attempt_stems}stems"
                assembled_dir.mkdir(exist_ok=True)
                
                for stem_name in stem_names:
                    combine_spleeter_stems( # Funkcja scalania WAV pozostaje bez zmian
                        [
                            chunk_output_dir / stem_name
                            for chunk_output_dir in chunk_output_dirs
                        ],
                        assembled_dir / stem_name,
                    )

                final_stems_dir = stems_dir / track_name
                if final_stems_dir.exists():
                    shutil.rmtree(final_stems_dir)
                os.replace(assembled_dir, final_stems_dir)
                print(
                    f"[audio-toolkit][base] Assembled {len(stem_names)} stems from "
                    f"{len(chunk_paths)} chunks using Demucs: {final_stems_dir}",
                    flush=True,
                )
                return attempt_stems
                
            except subprocess.CalledProcessError as exc:
                last_exc = exc
                if not is_kernel_kill_exit(exc.returncode):
                    raise
                print(
                    f"[audio-toolkit][base] Demucs was killed (likely OOM) using {attempt_stems} stems. Retrying with fewer stems.",
                    file=sys.stderr,
                    flush=True,
                )
            except subprocess.TimeoutExpired as exc:
                last_exc = exc
                print(
                    f"[audio-toolkit][base] Demucs exceeded timeout using {attempt_stems} stems.",
                    file=sys.stderr,
                    flush=True,
                )

    raise RuntimeError(f"Demucs failed for {audio_path}: {last_exc}")

"""
def run_spleeter_with_fallback(audio_path: Path, stems_dir: Path, stems_count: int, debug_steps: set[str] | None = None) -> int:
    candidate_counts = [stems_count]
    fallback = choose_recovery_stems(stems_count)
    if fallback is not None:
        candidate_counts.append(fallback)

    last_exc: subprocess.CalledProcessError | subprocess.TimeoutExpired | None = None
    stems_dir.mkdir(parents=True, exist_ok=True)
    track_name = audio_path.stem

    with tempfile.TemporaryDirectory(
        prefix="spleeter_chunks_",
        dir=stems_dir,
    ) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        chunk_paths = split_audio_into_chunks(audio_path, temp_dir / "chunks")

        for attempt in candidate_counts:
            attempt_dir = temp_dir / f"separated_{attempt}stems"
            attempt_dir.mkdir()
            try:
                for chunk_index, chunk_path in enumerate(chunk_paths, start=1):
                    print(
                        f"[audio-toolkit][base] Separating chunk {chunk_index}/{len(chunk_paths)} "
                        f"into {attempt} stems.",
                        flush=True,
                    )
                    cmd = [
                        str(VENV_BASE.parent / "spleeter"), "separate",
                        "-p", f"spleeter:{attempt}stems",
                        "-o", str(attempt_dir),
                        str(chunk_path),
                    ]
                    log_command("base", cmd, debug_steps)
                    subprocess.run(
                        cmd,
                        check=True,
                        timeout=SPLEETER_CHUNK_TIMEOUT_SECONDS,
                    )

                chunk_output_dirs = [
                    attempt_dir / chunk_path.stem
                    for chunk_path in chunk_paths
                ]
                stem_names = sorted(
                    path.name for path in chunk_output_dirs[0].glob("*.wav")
                )
                if set(stem_names) != SPLEETER_STEM_NAMES[attempt]:
                    raise RuntimeError(
                        f"Spleeter produced unexpected stems for {audio_path}: "
                        f"{stem_names}; expected {sorted(SPLEETER_STEM_NAMES[attempt])}"
                    )

                for chunk_output_dir in chunk_output_dirs[1:]:
                    actual_stem_names = sorted(
                        path.name for path in chunk_output_dir.glob("*.wav")
                    )
                    if actual_stem_names != stem_names:
                        raise RuntimeError(
                            "Spleeter produced inconsistent stems between audio chunks: "
                            f"{chunk_output_dir}"
                        )

                assembled_dir = temp_dir / f"assembled_{attempt}stems"
                assembled_dir.mkdir()
                for stem_name in stem_names:
                    combine_spleeter_stems(
                        [
                            chunk_output_dir / stem_name
                            for chunk_output_dir in chunk_output_dirs
                        ],
                        assembled_dir / stem_name,
                    )

                final_stems_dir = stems_dir / track_name
                if final_stems_dir.exists():
                    shutil.rmtree(final_stems_dir)
                os.replace(assembled_dir, final_stems_dir)
                print(
                    f"[audio-toolkit][base] Assembled {len(stem_names)} stems from "
                    f"{len(chunk_paths)} chunks: {final_stems_dir}",
                    flush=True,
                )
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
            except subprocess.TimeoutExpired as exc:
                last_exc = exc
                if attempt == 2:
                    break
                print(
                    f"[audio-toolkit][base] Spleeter exceeded the "
                    f"{SPLEETER_CHUNK_TIMEOUT_SECONDS}s chunk timeout using {attempt} stems. "
                    "Retrying all chunks with 2 stems.",
                    file=sys.stderr,
                    flush=True,
                )

    if last_exc is not None:
        if isinstance(last_exc, subprocess.TimeoutExpired):
            raise RuntimeError(
                f"Spleeter exceeded the {SPLEETER_CHUNK_TIMEOUT_SECONDS}s per-chunk timeout "
                f"while processing {audio_path}; no usable stems were produced. "
                "Increase SPLEETER_CHUNK_TIMEOUT_SECONDS or use shorter audio chunks."
            ) from last_exc
        raise RuntimeError(
            f"Spleeter was terminated by the OS while processing {audio_path}. "
            "This commonly means the Docker container is memory-constrained. "
            f"Requested stems: {stems_count}. The toolkit automatically retried with 2 stems, but the process still failed. "
            "Try a shorter audio file, reduce input length, or run the container with more RAM."
        ) from last_exc

    raise RuntimeError(f"Spleeter failed for {audio_path} without producing a valid result.")
"""

def run_process_pipeline(
    input_dir: Path,
    output_dir: Path,
    stems_count: int = 5,
    asr_language: str = "en",
    asr_model: str = "small",
    spectro_bool: bool = False,
    debug_steps: set[str] | None = None,
    stage: str = "full",
    skip_asr: bool = False,
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
    
    normalized_lang = normalize_asr_language(asr_language)

    execution_manifest = {
        "toolkit_version": "1.0.0",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "pipeline_stage": stage,
        "input_files": [p.name for p in audio_files],
        "processed_files_count": len(audio_files),
        "results": [],
        "asr_language": normalized_lang,
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
            actual_stems_count = run_demucs_with_fallback(audio_path, stems_dir, stems_count, debug_steps)
            # actual_stems_count = run_spleeter_with_fallback(audio_path, stems_dir, stems_count, debug_steps)
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
            print(
                f"[audio-toolkit][base] Analyzing {audio_path.name}.",
                flush=True,
            )
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
            print(
                f"[audio-toolkit] Processing stem {stem_file.name} for {audio_path.name}.",
                flush=True,
            )
            track_manifest["stems"][stem_type] = str(stem_file) if write_absolute_paths_bool else os.path.relpath(stem_file, track_out_dir)

            if stem_type in ["vocals", "vocal"] and stage in {"full", "asr"} and not skip_asr:
                # Whisper ASR
                cmd_asr = [
                    str(VENV_ASR), str(PROJECT_DIR / "src/modules/transcription.py"),
                    str(stem_file), str(asr_dir),
                    "--model", asr_model,
                    "--language", normalized_lang or "None",
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
                try:
                    subprocess.run(cmd_spectro, check=True)
                except subprocess.CalledProcessError as exc:
                    out_spectro.unlink(missing_ok=True)
                    print(
                        f"[audio-toolkit][base] Spectrogram generation failed for "
                        f"{stem_file.name} (exit code {exc.returncode}); skipping it.",
                        file=sys.stderr,
                        flush=True,
                    )
                else:
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
    parser.add_argument("--stems", type=int, default=6, choices=[2, 4, 6], help="Liczba stemów Demucs: 2, 4 lub 6 (domyślnie: 6 dla htdemucs_6s)")
    # parser.add_argument("--stems", type=int, default=5, choices=[2, 4, 5], help="Liczba stemów Spleeter (domyślnie: 5)")
    parser.add_argument("--lang", type=str, default="en", help="Język transkrypcji ASR (domyślnie: en)")
    parser.add_argument(
        "--no-asr", "--no-whisper", "--no-whisper-ai",
        action="store_true",
        dest="skip_asr",
        help="Pomija transkrypcję ASR/Whisper.",
    )
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

    ensure_venv_interpreters(stage=args.stage, skip_asr=args.skip_asr)

    manifest = run_process_pipeline(
        input_dir=args.input,
        output_dir=args.output,
        stems_count=args.stems,
        asr_language=args.lang,
        asr_model=args.model,
        spectro_bool=args.spectro,
        debug_steps=debug_steps,
        stage=args.stage,
        skip_asr=args.skip_asr,
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
