import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import audio_toolkit


def test_choose_recovery_stems_uses_lower_model_on_oom():
    assert audio_toolkit.choose_recovery_stems(5) == 2
    assert audio_toolkit.choose_recovery_stems(4) == 2
    assert audio_toolkit.choose_recovery_stems(2) is None
