# Audio Automation Toolkit

An automated audio-processing pipeline for source separation, music analysis, MIDI conversion, vocal transcription, and spectrogram generation.

Portfolio: [portfolio-website-development-eta-ten.vercel.app](https://portfolio-website-development-eta-ten.vercel.app/)

The project runs in Docker and uses three independent Python environments:

- Base environment — Demucs, audio analysis, and heuristics.
- TensorFlow environment — Basic Pitch.
- ASR environment — Whisper/faster-whisper or a compatible transcription module.

## Features

The toolkit can:

- separate audio into stems with Demucs using the `htdemucs_6s` model,
- analyze tempo/BPM, key, and tonality,
- convert melodic stems to MIDI,
- generate MIDI for drums using heuristics,
- generate MIDI for bass using heuristics,
- transcribe vocals to TXT, JSON, and SRT,
- generate spectrograms,
- save a consolidated JSON report.

## Supported input formats

The program searches the input directory for files with these extensions:

- `.wav`
- `.mp3`
- `.flac`
- `.m4a`
- `.ogg`

Files are processed in alphabetical order.

## Requirements

To run the project, you need:

- Docker,
- Docker Compose (optional),
- Internet access while building the image if dependencies are not cached,
- sufficient memory and disk space.

Basic Pitch, Whisper, and source separation can require significant hardware resources. For longer recordings, use a machine with more RAM or a GPU configured for the relevant libraries.

The Docker images use the digest-pinned `pytorch/pytorch:2.8.0-cuda12.6-cudnn9-runtime` base and Python 3.11. The base, TensorFlow, and ASR virtual environments install their separately pinned dependencies from `requirements/`. Dependency downloads use a persistent BuildKit cache and extended pip timeouts/retries to make large wheel downloads more reliable across builds. To use an NVIDIA GPU, install the NVIDIA Container Toolkit on the host and pass `--gpus all` to `docker run`; the container image does not include host GPU drivers.

## Project structure

```text
.
├── data
│   ├── input_audio
│   │   ├── [soundtrack] example 01.wav
│   │   └── [soundtrack] example 02.wav
│   └── output_results
├── Dockerfile
├── README.md
├── requirements
│   ├── asr.all.txt
│   ├── base.all.txt
│   └── tf.all.txt
└── src
    ├── audio_toolkit.py
    └── modules
        ├── analysis.py
        ├── conversion_basicpitch.py
        ├── heuristics.py
        ├── spectrogram.py
        └── transcription.py
```

## Build the Docker image

Run this command from the project root:

```/bin/bash
docker build -t audio-automation-toolkit .
```

To confirm that the image was created:

```/bin/bash
docker images audio-automation-toolkit
```

## Basic usage

The `data/input_audio` and `data/output_results` directories are mounted in the container under `/app/data`.

```/bin/bash
docker run --rm -it \
  -v "$(pwd)/data:/app/data" \
  audio-automation-toolkit \
  /app/data/input_audio \
  /app/data/output_results
```

## Process a batch with Docker Compose

Put audio files in `./input` and run the following from the project root. Compose builds the image if needed, processes the full batch, and writes results to `./output`:

```/bin/bash
docker compose run --build --rm audio-toolkit
```

The input folder is mounted read-only. The output folder is mounted for writing.

### Defaults

- Stem separation: 6 stems using `htdemucs_6s`.
- Transcription language: `en`.
- ASR model: `small`.
- Spectrogram generation: disabled.

## Write a JSON report

To save a consolidated report to a file:

```/bin/bash
docker run --rm -it \
  -v "$(pwd)/data:/app/data" \
  audio-automation-toolkit \
  /app/data/input_audio \
  /app/data/output_results \
  --json-out /app/data/output_results/manifest.json
```

The report includes:

- processed files,
- each source file's SHA-256 checksum, duration, sample rate, and channel count,
- output locations,
- audio analysis, including BPM and detected key/tonality,
- Demucs, Basic Pitch, and Whisper package/model versions where each stage ran,
- generated stems,
- MIDI files and transcription text,
- spectrograms, if enabled.
- per-track and overall processing time, status, and warnings.

Each track retains the existing `stems`, `midi`, `transcription`, and
`spectrograms` fields. The `outputs` field also provides lists of generated
stem, MIDI, and lyrics paths. Model package versions are read from the pinned
requirements files used to build the corresponding environments; the selected
model name is recorded separately.

## Vocal transcription

Use `--model` to choose the ASR model.

Example using a larger model:

```/bin/bash
docker run --rm -it \
  -v "$(pwd)/data:/app/data" \
  audio-automation-toolkit \
  /app/data/input_audio \
  /app/data/output_results \
  --model medium \
  --lang en
```

Example for Polish:

```/bin/bash
docker run --rm -it \
  -v "$(pwd)/data:/app/data" \
  audio-automation-toolkit \
  /app/data/input_audio \
  /app/data/output_results \
  --lang pl
```

Available models depend on the implementation used by `transcription.py`. Larger models usually provide better transcription quality but require more memory and processing time.

## Generate spectrograms

Enable spectrogram generation with `--spectro`:

```/bin/bash
docker run --rm -it \
  -v "$(pwd)/data:/app/data" \
  audio-automation-toolkit \
  /app/data/input_audio \
  /app/data/output_results \
  --spectro
```

`--spectrogram` is an alias for `--spectro`:

```/bin/bash
docker run --rm -it \
  -v "$(pwd)/data:/app/data" \
  audio-automation-toolkit \
  /app/data/input_audio \
  /app/data/output_results \
  --spectrogram
```

## Number of stems

The CLI accepts `--stems 6`, which selects Demucs' `htdemucs_6s` model:

```/bin/bash
docker run --rm -it \
  -v "$(pwd)/data:/app/data" \
  audio-automation-toolkit \
  /app/data/input_audio \
  /app/data/output_results \
  --stems 6
```

The default is `6`. If Demucs is terminated by the operating system or exceeds the per-chunk timeout, the toolkit retries with the four-stem `htdemucs` model.

## Output

For an input file such as:

```text
data/input_audio/example.wav
```

results are saved in a directory similar to:

```text
data/output_results/example/
├── analysis.json
├── stems
│   ├── vocals.wav
│   ├── drums.wav
│   ├── bass.wav
│   ├── other.wav
│   ├── guitar.wav
│   └── piano.wav
├── midi
│   ├── vocals.mid
│   ├── drums.mid
│   ├── bass.mid
│   ├── other.mid
│   ├── guitar.mid
│   └── piano.mid
├── asr
│   ├── vocals.txt
│   ├── vocals.json
│   └── vocals.srt
└── spectrograms
    ├── spectrogram.vocals.png
    ├── spectrogram.drums.png
    └── ...
```

The `spectrograms` directory is created only when `--spectro` or `--spectrogram` is enabled.

## CLI parameters

```text
audio_toolkit.py INPUT OUTPUT [OPTIONS]
```

### Positional arguments

| Argument | Description |
|---|---|
| `INPUT` | Directory containing audio files |
| `OUTPUT` | Directory where results are saved |

### Options

| Option | Default | Description |
|---|---:|---|
| `--stems` | `6` | Number of stems to request; valid value: `6` |
| `--lang` | `en` | Transcription language |
| `--model` | `small` | ASR model |
| `--json-out` | none | Path for the consolidated JSON report |
| `--spectro` | disabled | Generate spectrograms |
| `--spectrogram` | disabled | Alias for `--spectro` |

To display help:

```/bin/bash
docker run --rm -it audio-automation-toolkit --help
```

## Processing pipeline

For each audio file, the toolkit:

1. Finds supported audio files.
2. Splits the source into chunks of up to five minutes and separates each with Demucs.
3. Joins the chunks for each stem into one WAV file without loading the entire result into memory.
4. Analyzes tempo, key, and tonality.
5. Detects the vocal stem.
6. Transcribes vocals with ASR.
7. Converts the vocal stem to MIDI.
8. Converts drums to MIDI using heuristics.
9. Converts bass to MIDI using heuristics.
10. Converts the remaining stems to MIDI.
11. Optionally generates spectrograms.
12. Saves the JSON report.

## Python environments

The Docker image contains three independent virtual environments:

```text
/opt/venv311-base
/opt/venv311-tf
/opt/venv311-asr
```

This separates dependencies:

- `venv311-base` — audio tools, Demucs, and analysis,
- `venv311-tf` — TensorFlow and Basic Pitch,
- `venv311-asr` — speech-recognition libraries.

The application uses these environment variables:

```text
VENV_BASE
VENV_TF
VENV_ASR
```

## Input and output data

Audio files can take up a lot of disk space. We recommend:

- not adding large output files to the repository,
- keeping personal recordings local,
- using Git LFS if audio files need to be version-controlled,
- ignoring output directories in `.gitignore`.

Models and dependencies used by Demucs, Basic Pitch, and the ASR module may have separate license terms. Check the licenses of all components before using the project publicly.

## Limitations

- Separation quality depends on the recording and its quality.
- Audio-to-MIDI conversion may require manual correction.
- Heuristic bass and drum detection is not a substitute for full musical analysis.
- Transcription may contain errors when music includes reverb, noise, or multiple vocalists.
- The first run may take longer because models need to be downloaded.
- Processing multiple long files may require substantial RAM and disk space.

## Development ideas

Possible future improvements:

- configuration through YAML or TOML,
- support for processing a single file,
- logging to a file,
- per-file error reporting instead of stopping the entire pipeline,
- unit tests for modules,
- Docker image integration tests,
- GPU support,
- validation of generated MIDI files,
- an option to skip selected pipeline stages,
- recording the execution time of each stage.

## License

Distributed under the Python Software Foundation License / Open-Source guidelines. Check individual component licenses (Demucs, TensorFlow, Whisper) before commercial deployment.
