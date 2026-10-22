#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import whisper


def normalize_language(language: str | None) -> str | None:
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


def format_srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    
    hours = milliseconds // 3_600_000
    milliseconds %= 3_600_000
    
    minutes = milliseconds // 60_000
    milliseconds %= 60_000
    
    seconds_int = milliseconds // 1000
    milliseconds %= 1000
    
    return f"{hours:02d}:{minutes:02d}:{seconds_int:02d},{milliseconds:03d}"

def save_srt(segments: list[dict], output_file: Path) -> None:
    with output_file.open("w", encoding="utf-8") as file:
        for index, segment in enumerate(segments, start=1):
            start = float(segment["start"])
            end = float(segment["end"])
            text = segment["text"].strip()
            
            file.write(f"{index}\n")
            file.write(
                f"{format_srt_time(start)} --> "
                f"{format_srt_time(end)}\n"
            )
            file.write(f"{text}\n\n")

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rozpoznawanie mowy ze ścieżki vocals za pomocą OpenAI Whisper."
    )
    
    parser.add_argument(
        "input_audio",
        type=Path,
        help="Plik audio, np. vocals.wav",
    )
    
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Katalog na wyniki rozpoznawania mowy",
    )
    
    parser.add_argument(
        "--model",
        default="small",
        choices=["tiny", "base", "small", "medium", "large", "turbo"],
        help="Model Whisper, domyślnie: small",
    )
    
    parser.add_argument(
        "--language",
        default="pl",
        help="Język mowy, np. pl, en. Domyślnie: pl",
    )
    
    parser.add_argument(
        "--device",
        default=None,
        choices=["cpu", "cuda"],
        help="Urządzenie obliczeniowe. Domyślnie Whisper wybiera automatycznie.",
    )
    
    args = parser.parse_args()
    args.language = normalize_language(args.language)

    input_audio = args.input_audio.resolve()
    output_dir = args.output_dir.resolve()
    
    if not input_audio.exists():
        print(f"[Error] Plik nie istnieje: {input_audio}", file=sys.stderr)
        return 1
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_stem = input_audio.stem
    txt_path = output_dir / f"{output_stem}.txt"
    json_path = output_dir / f"{output_stem}.json"
    srt_path = output_dir / f"{output_stem}.srt"
    
    print(f"[ASR] Ładowanie modelu Whisper: {args.model}")
    
    model = whisper.load_model(
        args.model,
        device=args.device,
    )
    
    print(f"[ASR] Rozpoznawanie: {input_audio}")
    
    transcribe_options = {
        "language": args.language,
        "task": "transcribe",
        "verbose": False,
    }
    
    # FP16 działa poprawnie głównie na GPU CUDA.
    if args.device == "cpu":
        transcribe_options["fp16"] = False
    
    result = model.transcribe(
        str(input_audio),
        **transcribe_options,
    )
    
    text = result.get("text", "").strip()
    segments = result.get("segments", [])
    
    with txt_path.open("w", encoding="utf-8") as file:
        file.write(text)
        file.write("\n")
    
    json_result = {
        "input_audio": str(input_audio),
        "language": result.get("language", args.language),
        "text": text,
        "segments": segments,
    }
    
    with json_path.open("w", encoding="utf-8") as file:
        json.dump(
            json_result,
            file,
            ensure_ascii=False,
            indent=2,
        )
    
    save_srt(segments, srt_path)
    
    print(f"[ASR] Tekst: {txt_path}")
    print(f"[ASR] JSON:  {json_path}")
    print(f"[ASR] SRT:   {srt_path}")
    
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
