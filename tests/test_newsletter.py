from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from content_studio.extras.dailies import newsletter as n

ISSUE = """# AI Daily Newsletter — 2030-01-02
## 快讯

### 底层工具

- **Alpha 官方** | [甲产品发布](https://x.com/alpha/status/111)
  甲产品发布了新版本，价格下调。

- **Beta** | [乙论文](https://x.com/beta/status/999) — *更正链接*：[原帖](https://twitter.com/beta/status/222?s=20)
  乙团队公开了一篇论文。

### 工作流

- **Gamma** | [丙教程](https://example.com/post/)
  一篇教程。
## 深读

### [甲产品发布长文](https://x.com/alpha/status/111)

深读第一段。
深读第二段。
## 产品雷达

1. 一个点子
"""


def _write_item(root: Path, day: str, source: str, name: str, url: str, body: str) -> Path:
    folder = root / day / source
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.md"
    path.write_text(f"---\nid: 1\nsource: {source}\nurl: {url}\n---\n\n# {name}\n\n{body}\n", encoding="utf-8")
    return path


def test_parse_issue_splits_items_deep_and_markdown() -> None:
    p = n.parse_issue(ISSUE)
    assert p["title"].endswith("2030-01-02")
    kinds = [(s["name"], s["kind"], len(s["items"])) for s in p["sections"]]
    assert kinds == [("快讯", "items", 3), ("产品雷达", "markdown", 0)]
    first = p["sections"][0]["items"][0]
    assert (first["group"], first["source"], first["title"]) == ("底层工具", "Alpha 官方", "甲产品发布")
    assert first["summary"] == "甲产品发布了新版本，价格下调。"
    assert n.url_key("https://x.com/alpha/status/111") in p["deep"]
    assert "深读第二段" in p["deep"][n.url_key("https://x.com/alpha/status/111")]["body"]


def test_url_key_ignores_host_alias_query_and_slash() -> None:
    assert n.url_key("https://twitter.com/beta/status/222?s=20") == n.url_key("https://x.com/other/status/222")
    assert n.url_key("https://example.com/post/") == n.url_key("https://example.com/post")
    assert n.url_key("https://www.youtube.com/watch?v=abc&t=3") == n.url_key("https://youtu.be/abc")


def test_matching_uses_every_link_in_the_bullet(tmp_path: Path) -> None:
    _write_item(tmp_path, "30-01-02", "beta", "b", "https://x.com/beta/status/222", "乙的原文全文")
    _write_item(tmp_path, "30-01-02", "alpha", "a", "https://x.com/alpha/status/111", "甲的原文全文")
    (tmp_path / "30-01-02" / "000-30-01-02.md").write_text("---\nurl: https://x.com/alpha/status/111\n---\n摘要不是原文", encoding="utf-8")
    index = n.originals_index(tmp_path, "30-01-02")
    items = n.parse_issue(ISSUE)["sections"][0]["items"]
    beta = n.find_original(items[1], index)
    assert beta is not None and "乙的原文全文" in beta.read_text(encoding="utf-8")  # matched through 更正链接
    assert n.find_original(items[2], index) is None
    assert n.originals_index(tmp_path, "29-12-31") == {}


def test_snapshot_says_when_it_only_has_the_summary(tmp_path: Path) -> None:
    item = n.parse_issue(ISSUE)["sections"][0]["items"][0]
    now = datetime(2030, 1, 2, tzinfo=timezone.utc)
    full = n.snapshot_markdown(item, issue="AI 日报 · 2030-01-02", original={"meta": {}, "body": "原文正文"}, deep={"body": "深读"}, now=now)
    thin = n.snapshot_markdown(item, issue="AI 日报 · 2030-01-02", original=None, deep=None, now=now)
    assert "quality: 原文" in full and "## 原文" in full and "## 深读" in full
    assert "quality: 只有摘要" in thin and "## 原文" not in thin and "只找到摘要" in thin
    n.save_snapshot(tmp_path, 7, item, full)
    srcs = n.attached_sources(tmp_path, 7)
    assert len(srcs) == 1 and srcs[0]["title"] == "甲产品发布" and srcs[0]["url"] == "https://x.com/alpha/status/111"
    assert "原文正文" in srcs[0]["body"]
