import os
from pathlib import Path
import subprocess
import shutil

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/install-mac.sh"


def test_existing_installation_is_left_untouched(tmp_path):
    if not shutil.which("zsh"):
        pytest.skip("安装脚本在 macOS 的 zsh 上运行")
    app_dir = tmp_path / "existing"
    app_dir.mkdir()
    sentinel = app_dir / "profile.yaml"
    sentinel.write_text("me: 客户原配置")
    result = subprocess.run(["zsh", str(SCRIPT)], env={**os.environ, "APP_DIR": str(app_dir)}, capture_output=True, text=True)
    assert result.returncode == 1 and "不覆盖" in result.stdout
    assert sentinel.read_text() == "me: 客户原配置" and list(app_dir.iterdir()) == [sentinel]
