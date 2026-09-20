from importlib.util import find_spec
from pathlib import Path


def test_gap_analyzer_legacy_module_is_deleted():
    path = Path("modules/scheduler/logic/gap_analysis.py")

    assert not path.exists()
    assert find_spec("modules.scheduler.logic.gap_analysis") is None
