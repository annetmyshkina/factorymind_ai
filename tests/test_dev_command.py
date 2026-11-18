"""Локальный launcher не оставляет серверы и их дочерние процессы в фоне."""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("setsid") is None,
    reason="Совместный launcher рассчитан на Linux/WSL с setsid",
)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dev.sh"


def wait_for(predicate, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Процесс не достиг ожидаемого состояния")


def is_running(pid: int) -> bool:
    stat = Path(f"/proc/{pid}/stat")
    try:
        return stat.read_text().split(") ", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


@pytest.mark.parametrize("stop", ["sigint", "sigterm", "frontend_failure"])
def test_dev_stops_both_process_trees(tmp_path: Path, stop: str) -> None:
    mock = f"""#!{sys.executable}
import os
import subprocess
import sys
import time
from pathlib import Path

root = Path(os.environ['DEV_TEST_ROOT'])
name = Path(sys.argv[0]).name
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
(root / name).write_text(f'{{os.getpid()}} {{child.pid}}')
if os.environ['DEV_TEST_STOP'] == 'frontend_failure' and name == 'npm':
    while not (root / 'uv').exists():
        time.sleep(0.02)
    sys.exit(7)
time.sleep(60)
"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command in ("uv", "npm"):
        executable = bin_dir / command
        executable.write_text(mock)
        executable.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "DEV_TEST_ROOT": str(tmp_path),
        "DEV_TEST_STOP": stop,
    }
    process = subprocess.Popen(
        ["bash", str(SCRIPT)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    service_pids: list[int] = []
    try:
        wait_for(lambda: all((tmp_path / name).exists() for name in ("uv", "npm")))
        for name in ("uv", "npm"):
            service_pids.extend(map(int, (tmp_path / name).read_text().split()))
        if stop != "frontend_failure":
            process.send_signal(signal.SIGINT if stop == "sigint" else signal.SIGTERM)
        assert (
            process.wait(timeout=5)
            == {
                "sigint": 130,
                "sigterm": 143,
                "frontend_failure": 7,
            }[stop]
        )
        wait_for(lambda: not any(is_running(pid) for pid in service_pids))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for pid in service_pids:
            if is_running(pid):
                os.kill(pid, signal.SIGKILL)
