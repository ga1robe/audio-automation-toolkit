# Audio Automation Toolkit 🎧⚡

Automatyczne środowisko kontenerowe do batchowej analizy audio, separacji ścieżek (Spleeter), konwersji do sygnałów MIDI (Basic Pitch & Heurystyka) oraz rozpoznawania mowy z wokalizacji (OpenAI Whisper).

---

## Architektura Przepływu Danych

```mermaid
flowchart TD
    A[Plik Audio: WAV / MP3 / FLAC] --> B[Spleeter: Separacja Stemów]
    
    B --> C[Ścieżka Vocals]
    B --> D[Ścieżka Drums]
    B --> E[Ścieżka Bass]
    B --> F[Ścieżki Melodic / Other]
    
    A --> G[Audio Analysis: BPM, Key, Tonality]
    
    C --> H[OpenAI Whisper ASR]
    D --> I[Perkusyjna Heurystyka MIDI]
    E --> J[Basowa Heurystyka MIDI]
    F --> K[Basic Pitch Neural MIDI Transcriber]
    
    G --> I
    G --> J
    
    H --> L[Wyjście: TXT / SRT / JSON]
    I --> M[Wyjście: Drums MIDI]
    J --> N[Wyjście: Bass MIDI]
    K --> O[Wyjście: Stem MIDI]
    G --> P[Zbiórczy Raport JSON]
