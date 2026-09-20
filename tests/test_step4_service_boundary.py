import subprocess
import sys


def test_step4_logic_import_does_not_load_streamlit():
    probe = (
        "import sys; "
        "import modules.scheduler.logic.step4_service; "
        "assert 'streamlit' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
