# Audio Automation Toolkit

Automatyczny potok przetwarzania plików audio z wykorzystaniem separacji stemów, analizy muzycznej, konwersji do MIDI, transkrypcji wokalu oraz generowania spektrogramów.

Projekt uruchamiany jest w kontenerze Docker i korzysta z trzech niezależnych środowisk Python:

- środowisko bazowe — Spleeter, analiza audio i heurystyki,
- środowisko TensorFlow — Basic Pitch,
- środowisko ASR — Whisper/faster-whisper lub kompatybilny moduł transkrypcji.

## Możliwości

Toolkit umożliwia:

- separację ścieżki audio na stemów przy użyciu Spleeter,
- analizę tempa/BPM, tonacji i tonalności,
- konwersję ścieżek melodycznych do MIDI,
- heurystyczne generowanie MIDI dla perkusji,
- heurystyczne generowanie MIDI dla basu,
- transkrypcję wokalu do:
  - TXT,
  - JSON,
  - SRT,
- generowanie spektrogramów,
- zapis zbiorczego raportu JSON.

## Obsługiwane formaty wejściowe

Program wyszukuje w katalogu wejściowym pliki z rozszerzeniami:

- `.wav`
- `.mp3`
- `.flac`
- `.m4a`
- `.ogg`

Pliki przetwarzane są alfabetycznie.

## Wymagania

Do uruchomienia projektu potrzebne są:

- Docker,
- Docker Compose — opcjonalnie,
- dostęp do Internetu podczas budowania obrazu, jeżeli zależności nie są dostępne w cache,
- odpowiednia ilość pamięci RAM i miejsca na dysku.

Przetwarzanie Basic Pitch, Whisper oraz separacja stemów mogą wymagać znacznych zasobów sprzętowych. W przypadku dłuższych nagrań zalecane jest użycie komputera z większą ilością pamięci RAM lub GPU skonfigurowanym dla odpowiednich bibliotek.

## Struktura projektu

```text
.
├── data
│   ├── input\_audio
│   │   ├── [soundtrack] example 01.wav
│   │   └── [soundtrack] example 02.wav
│   └── output\_results
├── Dockerfile
├── README.md
├── requirements
│   ├── asr.all.txt
│   ├── base.all.1.txt
│   ├── base.all.txt
│   └── tf.all.txt
└── src
    ├── audio\_toolkit.py
    └── modules
        ├── analysis.py
        ├── conversion\_basicpitch.py
        ├── heuristics.py
        ├── spectrogram.py
        └── transcription.py
```

## Budowanie obrazu Docker

W katalogu głównym projektu wykonaj:
```/bin/bash

docker build -t audio-automation-toolkit .
```
Można sprawdzić, czy obraz został utworzony:
```/bin/bash

docker images audio-automation-toolkit
```
## Podstawowe uruchomienie

Katalogi data/input_audio oraz data/output_results są mapowane do kontenera jako /app/data.
```/bin/bash

docker run --rm -it \\
  -v "\$(pwd)/data:/app/data" \\
  audio-automation-toolkit \\
  /app/data/input\_audio \\
  /app/data/output\_results
```
> Dla debugowania kolejności i logowania etapów `base -> tf -> asr` użyj opcji `--debug` lub `--debug-steps`; zobacz sekcję "Debugowanie etapów" poniżej.
### Domyślne ustawienia:

- separacja na 5 stemów,
- język transkrypcji: en,
- model ASR: small,
- spektrogramy: wyłączone.

## Uruchomienie z raportem JSON

Aby zapisać zbiorczy raport do pliku:

```/bin/bash
docker run --rm -it \\
  -v "\$(pwd)/data:/app/data" \\
  audio-automation-toolkit \\
  /app/data/input\_audio \\
  /app/data/output\_results \\
  --json-out /app/data/output\_results/manifest.json
```

Raport zawiera informacje o:

- przetworzonych plikach,
- lokalizacji wyników,
- analizie audio,
- wygenerowanych stemach,
- plikach MIDI,
- transkrypcji,
- spektrogramach, jeżeli zostały włączone.

## Transkrypcja wokalu

Do wyboru modelu ASR służy parametr --model.

Przykład z większym modelem:

```/bin/bash
docker run --rm -it \\
  -v "\$(pwd)/data:/app/data" \\
  audio-automation-toolkit \\
  /app/data/input\_audio \\
  /app/data/output\_results \\
  --model medium \\
  --lang en
```

Przykład dla języka polskiego:

```/bin/bash
docker run --rm -it \\
  -v "\$(pwd)/data:/app/data" \\
  audio-automation-toolkit \\
  /app/data/input\_audio \\
  /app/data/output\_results \\
  --lang pl
```

Dostępne modele zależą od implementacji użytej w module transcription.py. Większe modele zwykle zapewniają lepszą jakość transkrypcji, ale wymagają więcej pamięci i czasu.

## Generowanie spektrogramów

Aby włączyć generowanie spektrogramów, dodaj opcję --spectro:

```/bin/bash
docker run --rm -it \\
  -v "\$(pwd)/data:/app/data" \\
  audio-automation-toolkit \\
  /app/data/input\_audio \\
  /app/data/output\_results \\
  --spectro
```

Opcja --spectrogram jest aliasem dla --spectro:

```/bin/bash
docker run --rm -it \\
  -v "\$(pwd)/data:/app/data" \\
  audio-automation-toolkit \\
  /app/data/input\_audio \\
  /app/data/output\_results \\
  --spectrogram
```

## Liczba stemów

Program obsługuje następujące warianty separacji:
```/bin/bash
--stems 2
--stems 4
--stems 5
```

Przykład:
```/bin/bash
docker run --rm -it \\
  -v "\$(pwd)/data:/app/data" \\
  audio-automation-toolkit \\
  /app/data/input\_audio \\
  /app/data/output\_results \\
  --stems 4
```

Domyślna wartość to:
```text
5
```

## Debugowanie etapów

W trakcie rozwiązywania problemów warto włączyć logowanie komend uruchamianych w poszczególnych środowiskach. Domyślnie debug jest wyłączony, aby nie zatruwać standardowego działania aplikacji.

### Flaga skrócona

```/bin/bash
docker run --rm -it \
  -v "\$(pwd)/data:/app/data" \
  audio-automation-toolkit \
  /app/data/input\_audio \
  /app/data/output\_results \
  --debug
```

To jest alias do:
```/bin/bash
--debug-steps base tf asr
```

### Flaga szczegółowa

```/bin/bash
docker run --rm -it \
  -v "\$(pwd)/data:/app/data" \
  audio-automation-toolkit \
  /app/data/input\_audio \
  /app/data/output\_results \
  --debug-steps base tf
```

lub tylko dla ASR:

```/bin/bash
docker run --rm -it \
  -v "\$(pwd)/data:/app/data" \
  audio-automation-toolkit \
  /app/data/input\_audio \
  /app/data/output\_results \
  --debug-steps asr
```

Po użyciu tej flagi konsola pokaże dokładnie, który interpreter i który plik/skrypt są wywoływane w kolejności: `base -> tf -> asr`. Dzięki temu łatwiej zlokalizować etap, który powoduje błąd lub przeciążenie zasobów.

## Wyniki

Dla pliku:
```text
data/input\_audio/example.wav
```

wyniki zapisywane są w katalogu podobnym do:
```text
data/output\_results/example/
├── analysis.json
├── stems
│   ├── vocals.wav
│   ├── drums.wav
│   ├── bass.wav
│   ├── piano.wav
│   └── other.wav
├── midi
│   ├── example-vocals.mid
│   ├── example-drums.mid
│   ├── example-bass.mid
│   ├── example-piano.mid
│   └── example-other.mid
├── asr
│   ├── vocals.txt
│   ├── vocals.json
│   └── vocals.srt
└── spectrograms
    ├── spectrogram.vocals.png
    ├── spectrogram.drums.png
    └── ...
```

Katalog spectrograms pojawia się tylko wtedy, gdy użyto opcji `--spectro` lub `--spectrogram`.

Parametry CLI
```text
audio\_toolkit.py INPUT OUTPUT [OPTIONS]
```

### Parametry pozycyjne

| Parametr | Opis |
|---|---|
| `INPUT` | Katalog z plikami audio |
| `OUTPUT` | Katalog przeznaczony na wyniki |

### Opcje

| Opcja | Domyślna wartość | Opis |
|---|---:|---|
| `--stems` | `5` | Liczba stemów Spleeter: `2`, `4` lub `5` |
| `--lang` | `en` | Język transkrypcji |
| `--model` | `small` | Model ASR |
| `--json-out` | brak | Ścieżka zbiorczego raportu JSON |
| `--spectro` | wyłączone | Generowanie spektrogramów |
| `--spectrogram` | wyłączone | Alias dla `--spectro` |

Pomoc:
```/bin/bash
docker run --rm -it audio-automation-toolkit --help
```

## Przebieg przetwarzania

Dla każdego pliku audio wykonywane są następujące kroki:

1. Wyszukanie obsługiwanych plików audio.
2. Separacja źródła na stemów przy użyciu Spleeter.
3. Analiza tempa, tonacji i tonalności.
4. Wykrycie ścieżki wokalnej.
5. Transkrypcja wokalu z użyciem ASR.
6. Konwersja ścieżki wokalnej do MIDI.
7. Heurystyczna konwersja perkusji do MIDI.
8. Heurystyczna konwersja basu do MIDI.
9. Konwersja pozostałych stemów do MIDI.
10. Opcjonalne wygenerowanie spektrogramów.
11. Zapis raportu JSON.

## Środowiska Python

Obraz Docker zawiera trzy niezależne środowiska wirtualne:

```text
/opt/venv311-base
/opt/venv311-tf
/opt/venv311-asr
```

Takie rozwiązanie pozwala odseparować zależności:

- `venv311-base` — podstawowe narzędzia audio, Spleeter i analiza,
- `venv311-tf` — TensorFlow i Basic Pitch,
- `venv311-asr` — biblioteki związane z rozpoznawaniem mowy.

Zmienne środowiskowe wykorzystywane przez aplikację:

```text
VENV_BASE
VENV_TF
VENV_ASR
```

## Uwagi dotyczące danych wejściowych i wyjściowych

Pliki audio mogą zajmować dużo miejsca. Zaleca się:

- nie dodawać dużych plików wynikowych do repozytorium,
- przechowywać własne nagrania lokalnie,
- używać Git LFS, jeśli pliki audio mają być wersjonowane,
- ignorować katalogi wynikowe w `.gitignore`.

Modele i zależności używane przez Spleeter, Basic Pitch oraz moduł ASR mogą podlegać odrębnym warunkom licencyjnym. Przed publicznym użyciem projektu należy sprawdzić licencje wszystkich wykorzystanych komponentów.

## Ograniczenia

- Jakość separacji zależy od rodzaju i jakości nagrania.
- Wyniki konwersji audio do MIDI mogą wymagać ręcznej korekty.
- Heurystyczna detekcja basu i perkusji nie zastępuje pełnej analizy muzycznej.
- Transkrypcja może zawierać błędy przy muzyce z pogłosem, hałasem lub wieloma wokalami.
- Pierwsze uruchomienie może być dłuższe ze względu na pobieranie modeli.
- Przetwarzanie wielu długich plików może wymagać dużej ilości pamięci RAM i miejsca na dysku.

## Rozwój projektu

Przykładowy kierunek dalszego rozwoju:

- obsługa konfiguracji przez plik YAML lub TOML,
- możliwość przetwarzania pojedynczego pliku,
- logowanie do pliku,
- raportowanie błędów per plik zamiast zatrzymywania całego potoku,
- testy jednostkowe modułów,
- testy integracyjne obrazu Docker,
- obsługa GPU,
- walidacja wygenerowanych plików MIDI,
- możliwość pomijania wybranych etapów potoku,
- zapis czasu wykonania poszczególnych etapów.


