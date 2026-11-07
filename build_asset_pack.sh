#!/usr/bin/env bash
set -e

# Ścieżki bazowe
TOOLKIT_DIR="/home/robert/Muzyka/Devs/audio-automation-toolkit"
OUTPUT_DIR="$TOOLKIT_DIR/data/output_results"
GLOBAL_PRESETS_DIR="$TOOLKIT_DIR/presets_template"  # Miejsce z plikiem .sf2 i plikami CSV
ASSET_PACKS_BASE="/home/robert/Muzyka/Asset-packs"

# Nazwa nowej paczki
PACK_NAME="$1"

if [ -z "$PACK_NAME" ]; then
    /bin/echo "Błąd: Podaj nazwę paczki, np.: ./build_asset_pack.sh \"[Asset-pack] Kotołak - New World Order\""
    exit 1
fi

DEST_DIR="$ASSET_PACKS_BASE/$PACK_NAME"
/bin/echo "=== Tworzenie Paczki: $PACK_NAME ==="
/bin/mkdir -p "$DEST_DIR"

# 1. Kopiowanie globalnych plików manifestu (jeśli istnieją)
/bin/cp "$OUTPUT_DIR"/manifest_*.json "$DEST_DIR"/ 2>/dev/null || true

# 2. Kopiowanie jednego zbiórczego katalogu presets do korzenia paczki
if [ -d "$GLOBAL_PRESETS_DIR" ]; then
    /bin/echo "Kopiowanie globalnego katalogu presets..."
    /bin/cp -r "$GLOBAL_PRESETS_DIR" "$DEST_DIR/presets"
fi

CURRENT_EPOCH=$(date +%s)
CURRENT_DATE=$(date +"%B %Y")

# 3. Przetwarzanie poszczególnych podkatalogów utworów
for TRACK_DIR in "$OUTPUT_DIR"/*/; do
    [ -d "$TRACK_DIR" ] || continue
    TRACK_NAME=$(basename "$TRACK_DIR")
    
    # Pomijamy katalogi systemowe / nietypowe
    if [[ "$TRACK_NAME" == "presets" ]]; then continue; fi
    
    /bin/echo "--> Przetwarzanie utworu: $TRACK_NAME"
    TARGET_TRACK_DIR="$DEST_DIR/$TRACK_NAME"
    /bin/mkdir -p "$TARGET_TRACK_DIR"
    
    # Kopiowanie wygenerowanych podkatalogów (stems, midi, asr, spectrograms, analysis.json)
    /bin/cp -r "$TRACK_DIR"* "$TARGET_TRACK_DIR/"
    
    # --- Generowanie README.md ---
    README_FILE="$TARGET_TRACK_DIR/README.md"
    /bin/cp "$TOOLKIT_DIR/README_template.md" "$README_FILE"
    
    # Podmiana nazwy utworu w 1. linii[cite: 12]
    /bin/sed -i "1s/.*/$TRACK_NAME/" "$README_FILE"
    # Podmiana daty utworzenia[cite: 10]
    /bin/sed -i "s/\*\*Created\*\*: .*/\*\*Created\*\*: $CURRENT_DATE/" "$README_FILE"
    # Podmiana Unix Epoch[cite: 11]
    /bin/sed -i "s/\*\*Pack ID\*\*: .*/\*\*Pack ID\*\*: $CURRENT_EPOCH (Unix Epoch)/" "$README_FILE"
    
    # --- Generowanie audio_basic_meta.csv ---
    META_FILE="$TARGET_TRACK_DIR/audio_basic_meta.csv"
    > "$META_FILE"
    
    /bin/find "$TARGET_TRACK_DIR/stems" -type f \( -iname "*.ogg" -o -iname "*.wav" -o -iname "*.mp3" \) | while read -r f; do
        rel_f=$(/bin/basename "$f")
        dur=$(/bin/ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$f")
        sr=$(/bin/ffprobe -v error -show_entries stream=sample_rate -of default=noprint_wrappers=1:nokey=1 "$f" | head -n1)
        bits=$(/bin/ffprobe -v error -select_streams a:0 -show_entries stream=bits_per_raw_sample -of default=noprint_wrappers=1:nokey=1 "$f")
        /bin/echo "\"stems/$rel_f\",$dur,$sr,${bits:-16}" >> "$META_FILE"
    done
done

/bin/echo "=== Paczka gotowa w: $DEST_DIR ==="

# 4. Opcjonalne pakowanie do ZIP
read -p "Czy chcesz zpakować paczkę do pliku ZIP w $ASSET_PACKS_BASE? (t/n): " ZIP_CONFIRM
if [[ "$ZIP_CONFIRM" =~ ^[Tt]$ ]]; then
    cd "$ASSET_PACKS_BASE"
    /bin/zip -r "${PACK_NAME}.zip" "$PACK_NAME"
    /bin/echo "Plik ZIP został utworzony: $ASSET_PACKS_BASE/${PACK_NAME}.zip"
fi
