"""10/12 作者：回复只能用他 Obsidian 原始输出里的原话，park-writing 只删、挪、补成一句。"""
from datetime import datetime, timedelta
import json

import pytest

from content_studio.extras.xline import x_daily, x_replies

NOW = datetime(2026, 10, 12, 10, tzinfo=x_daily.BJ)


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    x_replies._RAW_CACHE.update(key=None, lines=[], df={}, n=0)


@pytest.fixture
def vault(tmp_path):
    raw = tmp_path / "vault" / "003_原始输出"
    (raw / "_整理前").mkdir(parents=True)
    (raw / "AI 工具.md").write_text("---\ndate: 2026-09-01\n---\n# AI 工具\n\n我觉得 AI 工具最重要的是能不能稳定交付结果。光演示一次漂亮的成品没有用。\n\n交易要做减法，每天少做决定。", encoding="utf-8")
    (raw / "客户咨询记录.md").write_text("客户说 AI 工具很好用，这句不该被拿来回复。", encoding="utf-8")
    (raw / "_整理前" / "旧.md").write_text("AI 工具的旧版本原话，整理前的不读。", encoding="utf-8")
    return tmp_path / "vault"


def post(tid, text):
    return {"id": tid, "url": f"https://x.com/u/status/{tid}", "author": "作者", "text": text, "category": "AI",
            "published_at": (NOW - timedelta(hours=1)).isoformat()}


def test_lines_come_only_from_his_raw_notes(vault):
    lines = x_replies.raw_lines(vault)
    texts = [x["text"] for x in lines]
    assert "我觉得 AI 工具最重要的是能不能稳定交付结果。" in texts
    assert not any("客户说" in t or "旧版本" in t for t in texts)  # 客户 / 咨询、整理前的不读
    best = x_replies.match_lines("这个 AI 工具的演示视频很炸", lines)
    assert best[0]["note"] == "003_原始输出/AI 工具.md" and "AI 工具" in best[0]["text"]


def test_reply_is_his_line_tidied_and_made_up_ones_are_dropped(vault):
    prompts = []

    def model(system, prompt, _):
        prompts.append(prompt)
        rows = json.loads(prompt.split("原帖：\n", 1)[1])
        assert all(r["park_lines"] for r in rows)
        return {"text": json.dumps({"replies": [
            {"id": "1", "source": ["0"], "text": "AI 工具最重要的，是能不能稳定交付结果。"},
            {"id": "2", "source": ["0"], "text": "我认为模型能力决定了一切，未来的竞争就是算力的竞争。"},  # 编的
        ]}, ensure_ascii=False)}

    made = x_replies.draft([post("1", "AI 工具演示都很炫"), post("2", "AI 工具的演示又刷屏了")], soul="", style="park-writing",
                           turn_fn=model, auto=True, now=NOW, vault_root=vault)
    assert made == 1
    data = x_replies.x_daily.load(x_replies.path())["days"]["2026-10-12"]
    assert data["1"]["state"] == "approved" and data["1"]["source_note"] == "003_原始输出/AI 工具.md"
    assert data["2"]["state"] == "skip"
    assert "park-writing" in prompts[0] or "只能用 作者自己的原话" in prompts[0]


def test_no_related_line_means_no_reply_and_no_model_call(vault):
    made = x_replies.draft([post("3", "今天的足球比赛太精彩了")], soul="", style="", now=NOW, vault_root=vault,
                           turn_fn=lambda *a: pytest.fail("没有相关原话就不该调模型"))
    assert made == 0
    assert x_replies.x_daily.load(x_replies.path())["days"]["2026-10-12"]["3"]["state"] == "skip"


def test_grounded_allows_a_few_bridge_chars_only():
    line = "我觉得 AI 工具最重要的是能不能稳定交付结果。"
    assert x_replies.grounded("AI 工具最重要的，是能不能稳定交付结果。", [line])
    assert not x_replies.grounded("AI 工具最重要的是能不能稳定交付结果，这是我十年创业得出的结论。", [line])
