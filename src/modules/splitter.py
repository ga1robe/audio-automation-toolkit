from pathlib import Path
from pydub import AudioSegment
from pydub.silence import split_on_silence

def split_dj_set_by_silence(input_path: Path, output_dir: Path, min_silence_len=3000, silence_thresh=-40):
    """
    Dzieli duży plik audio na mniejsze fragmenty na podstawie ciszy.
    min_silence_len: czas trwania ciszy w milisekundach (np. 3000 = 3 sekundy)
    silence_thresh: próg głośności w dBFS (np. -40 dB)
    """
    print(f"Wczytywanie pliku audio do podziału: {input_path.name}...")
    audio = AudioSegment.from_file(str(input_path))
    
    print("Wyszukiwanie punktów podziału (cisza/spadek głośności)...")
    chunks = split_on_silence(
        audio,
        min_silence_len=min_silence_len,
        silence_thresh=silence_thresh,
        keep_silence=1000 # zachowaj 1 sekundę ciszy na początku/końcu każdego utworu
    )
    
    output_dir.mkdir(parents=True, exist_ok=True)
    split_files = []
    
    for i, chunk in enumerate(chunks):
        chunk_name = output_dir / f"track_{i+1:02d}.wav"
        print(f"Eksportowanie fragmentu: {chunk_name.name} (czas trwania: {len(chunk)/1000:.1f}s)")
        chunk.export(chunk_name, format="wav")
        split_files.append(chunk_name)
        
    return split_files