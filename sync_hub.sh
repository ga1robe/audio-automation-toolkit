#!/usr/bin/env bash

# Zatrzymanie skryptu w przypadku błędu
set -e

HUB_DIR="$HOME/AudioEngineeringHub"
cd "$HUB_DIR"

/bin/echo "=== [Audio Engineering Hub] Rozpoczynanie synchronizacji git ==="

# Sprawdzenie statusu repozytorium
/usr/bin/git status

# Dodanie wszystkich zmian (notatki, manifesty, aktualizacje kodu)
/usr/bin/git add .

# Pobranie aktualnej daty i godziny do wiadomości commitu
COMMIT_MSG="Auto-sync: $(date '+%Y-%m-%d %H:%M:%S')"

# Tworzenie commitu (jeśli są zmiany)
if /usr/bin/git diff-index --quiet HEAD --; then
    echo "Brak nowych zmian do zatwierdzenia."
else
    /usr/bin/git commit -m "$COMMIT_MSG"
    /bin/echo "Utworzono commit: $COMMIT_MSG"
fi

# Wypchnięcie zmian do zdalnego repozytorium (np. GitHub)
/bin/echo "Wysyłanie zmian do zdalnego repozytorium..."
/usr/bin/git push origin main

/bin/echo "=== Synchronizacja zakończona pomyślnie! ==="
