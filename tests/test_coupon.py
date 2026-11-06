"""付息稿（10/2 作者）：骨架后面的一步——开头发债、每 10 秒付息、最后兑付本金。"""
from __future__ import annotations

from pathlib import Path
import sys
import time

import pytest

from content_studio import coupon, outline
from content_studio.writer import WriterError
from tests.test_web import client  # noqa: F401 - fixture


def _good(rows: int = 10, step: int = 10) -> str:
    lines = [f"| {i * step // 60}:{i * step % 60:02d}–{(i + 1) * step // 60}:{(i + 1) * step % 60:02d} | 第 {i} 句 | 新判断 | |" for i in range(rows)]
    return ("<<<ARTICLE>>>\n# 6000 粉丝\n\n**本金**：我问每个客户的三段问题\n\n### 发债\n| 时间 | 口播 | 息 | 画面 |\n|---|---|---|---|\n"
            + "\n".join(lines) + "\n\n## 利息账本\n- 付息 10 笔\n\n## 删掉的\n- 说错重来\n<<<END>>>")


def test_extract_wants_a_principal_a_ledger_and_interest_every_few_seconds() -> None:
    assert coupon.extract(_good()).startswith("# 6000 粉丝")
    with pytest.raises(WriterError, match="本金"):
        coupon.extract(_good().replace("**本金**：我问每个客户的三段问题", ""))
    with pytest.raises(WriterError, match="利息账本"):
        coupon.extract(_good().replace("## 利息账本", "## 账"))
    with pytest.raises(WriterError, match="至少要"):
        coupon.extract(_good(rows=4))
    with pytest.raises(WriterError, match="超过 15 秒"):
        coupon.extract(_good(step=20))  # 20 秒一行：中间很久没付息
    with pytest.raises(WriterError, match="格式"):
        coupon.extract("没有标记")


def test_write_coupon_follows_the_workflow_file_and_the_skeleton(tmp_path: Path) -> None:
    flows = tmp_path / "workflows"
    flows.mkdir()
    (flows / coupon.FRAMEWORK_FILE).write_text("---\nname: 付息稿\n---\n# 付息稿\n每 10 秒付一次息。", encoding="utf-8")
    seen = []
    tries = iter(["坏的输出", _good()])

    def fn(prompt: str) -> str:
        seen.append(prompt)
        return next(tries)

    topic = {"id": 7, "title": "6000 粉丝", "memo": "", "note_paths": "[]"}
    res = coupon.write_coupon(topic, skeleton="## 中间骨架\n### 论点 A：后端", vault_raw=str(tmp_path / "vault"), drafts_dir=tmp_path / "drafts",
                              write_fn=fn, workflows=flows)
    assert Path(res["path"]).read_text(encoding="utf-8").startswith("# 6000 粉丝")
    assert "每 10 秒付一次息" in seen[0] and "论点 A：后端" in seen[0] and "name: 付息稿" not in seen[0]
    assert "上一次输出有问题" in seen[1]  # 第一次格式不对：带着原因重写一次
    assert coupon.read_coupon(tmp_path / "drafts", 7)["mode_label"] == "密度"
    with pytest.raises(WriterError, match="先写骨架"):
        coupon.write_coupon(topic, skeleton=" ", vault_raw="", drafts_dir=tmp_path / "drafts", write_fn=fn, workflows=flows)
    with pytest.raises(WriterError, match="找不到"):
        coupon.load_framework(tmp_path / "nowhere")


def test_coupon_follows_the_skeleton_on_the_video_page(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    topic = client.post("/api/topics", json={"title": "6000 粉丝", "formats": "video"}).json()
    assert client.get(f"/api/topics/{topic['id']}/coupon").json() == {"running": False, "error": None, "coupon": None}
    assert client.post(f"/api/topics/{topic['id']}/coupon").status_code == 400  # 还没有骨架
    # 付息稿的规则在 Anna 的工作流文件里；假的写作命令照格式回一稿
    (tmp_path / "workflows" / coupon.FRAMEWORK_FILE).write_text("# 付息稿\n每 10 秒付一次息。", encoding="utf-8")
    fake = tmp_path / "fake_coupon.py"
    fake.write_text(f"import sys; sys.stdin.read(); print({_good()!r})", encoding="utf-8")
    monkeypatch.setenv(coupon.COUPON_COMMAND_ENV, f"{sys.executable} {fake}")
    client.post(f"/api/topics/{topic['id']}/outline")  # 骨架写完，自动接着写付息稿
    for _ in range(100):
        d = client.get(f"/api/topics/{topic['id']}/coupon").json()
        if d["coupon"] and not d["running"]:
            break
        time.sleep(0.05)
    assert d["coupon"]["markdown"].startswith("# 6000 粉丝") and d["error"] is None
    saved = client.put(f"/api/topics/{topic['id']}/coupon", json={"markdown": "# 改过的"}).json()
    assert saved["markdown"] == "# 改过的\n"
    assert outline.FRAMEWORK_FILE != coupon.FRAMEWORK_FILE


def test_the_coupon_tab_is_actually_shown_on_the_video_page() -> None:
    """10/2：页签注册了，但视频页只显示 TAB_ORDER 里的几个——漏了它，作者 刷新了也看不到。"""
    import re

    js = (Path(__file__).resolve().parents[1] / "src/content_studio/static/video.js").read_text(encoding="utf-8")
    order = re.search(r"const TAB_ORDER = \[([^\]]*)\]", js).group(1)
    assert "'coupon'" in order and order.index("'outline'") < order.index("'coupon'") < order.index("'edit'")
    assert "key: 'coupon'" in js


def test_the_outline_tab_keeps_checking_until_the_skeleton_is_written() -> None:
    """10/5 作者：骨架写完了，不刷新网页就不显示。「正在写」那一屏要自己回头查，查的时候不能用 5 秒的缓存。"""
    js = (Path(__file__).resolve().parents[1] / "src/content_studio/static/video.js").read_text(encoding="utf-8")
    running = js[js.index("if (topic.outline_state === 'running') {"):]
    running = running[:running.index("return;")]
    assert "setTimeout(" in running and "invalidateWork()" in running and "VD.outline = null" in running
