"""设置 · 流程（10/9 作者）：流程顺序是他那一套，固定不让调；用户只能开关其中的组件。
关掉的那一步跳过、后面照常走；接口不拦，以前做出来的照样打得开。"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_studio import approvals, edition, pack_auto, schedule
from tests.test_approvals import _fps
from tests.test_pack_auto import ARMED, ap
from tests.test_web import client  # noqa: F401


def test_user_switches_only_turn_off_switchable_components() -> None:
    assert edition.off(None, ["coupon", "portal", "没有这个"]) == frozenset({"coupon"})  # 整页的不归用户开关
    assert not edition.on("coupon", None, ["coupon"])
    assert edition.on("qa", None, ["coupon"])
    assert edition.off({"edition": "trial"}, ["qa"]) == edition.EDITIONS["trial"] | {"qa"}


def test_user_switches_never_block_routes() -> None:
    assert edition.blocked("/api/xline/daily", None) is None  # blocked 只看版本，不看用户关了什么


def test_settings_save_switches_and_state_reports_them(client: TestClient) -> None:  # noqa: F811
    saved = client.put("/api/settings", json={"components_off": ["motion", "coupon", "coupon"]}).json()
    assert saved["components_off"] == ["coupon", "motion"]
    ed = client.get("/api/state").json()["edition"]
    assert ed["user_off"] == ["coupon", "motion"] and ed["cut"] == []
    assert {"coupon", "motion"} <= set(ed["off"])
    # 10/20：xline 管着写稿页和拍后批注，不再让人在设置里关
    assert client.put("/api/settings", json={"components_off": ["xline"]}).status_code == 400
    assert set(ed["switches"]) == set(edition.SWITCHES)
    assert client.get("/api/xline").status_code == 200  # 关了也打得开
    assert client.put("/api/settings", json={"components_off": ["portal"]}).status_code == 400
    client.put("/api/settings", json={"components_off": []})
    assert client.get("/api/state").json()["edition"]["user_off"] == []


def test_evidence_sheet_does_not_start_itself_when_proof_is_off(client: TestClient, tmp_path: Path, monkeypatch) -> None:  # noqa: F811
    from content_studio.extras.proof import proof
    from tests.test_proof import SHEET, SKELETON, _run

    store = client.app.state.store
    tid = client.post("/api/topics", json={"title": "AI 赚钱"}).json()["id"]
    store.set_focus(tid)
    sk = tmp_path / "drafts" / f"topic-{tid}" / "skeleton.md"
    sk.parent.mkdir(parents=True, exist_ok=True)
    sk.write_text(SKELETON, encoding="utf-8")
    store.update_topic(tid, outline_path=str(sk))
    monkeypatch.setattr(proof, "run", lambda base, title, skeleton, now: _run(base, skeleton, SHEET))
    client.put("/api/settings", json={"components_off": ["proof"]})
    assert client.app.state.auto_proof_once() is None  # 开着的话这里就自己开始了
    client.put("/api/settings", json={"components_off": []})
    assert client.app.state.auto_proof_once() == tid
    import time

    for _ in range(50):  # 等后台那一轮跑完，别留线程到下一个测试
        if not client.get(f"/api/topics/{tid}/proof").json()["running"]:
            break
        time.sleep(0.05)


def test_schedule_counts_a_pack_as_written_without_coupon_when_coupon_is_off(tmp_path: Path) -> None:
    outline = tmp_path / "骨架.md"
    outline.write_text("骨架", encoding="utf-8")
    topic = {"id": 7, "outline_path": str(outline)}
    assert schedule.needs_writing(topic, tmp_path)  # 付息稿开着：还没写付息稿就还要写
    assert not schedule.needs_writing(topic, tmp_path, coupon=False)
    assert schedule.needs_writing({"id": 8}, tmp_path, coupon=False)  # 骨架照样要写


def test_pack_layout_does_not_wait_for_figs_when_figs_are_off() -> None:
    needed = {"article", "wx"}  # _pack_needed 在插图关掉时把 figs 拿掉
    state = ap(copy="locked", article="locked")
    assert pack_auto.plan(ARMED, state, set(), title="只有6000粉丝", xhs=False, needed=needed) == [("start", "wx")]
    rows = pack_auto.view({"armed": True}, ap(copy="locked"), set(), xhs=False, needed=needed)
    assert [r["key"] for r in rows] == ["article", "wx"]
    assert "插图" not in next(r["note"] for r in rows if r["key"] == "wx")


def test_layout_can_be_locked_without_figs_when_figs_are_off(tmp_path: Path) -> None:
    folder = tmp_path / "topic-1"
    fps = _fps(tmp_path)
    approvals.set_approval(folder, "copy", True, fps)
    approvals.set_approval(folder, "article", True, fps)
    with pytest.raises(approvals.ApprovalError, match="上一步"):
        approvals.set_approval(folder, "wx", True, fps)
    st = approvals.set_approval(folder, "wx", True, fps, skip={"figs"})
    assert st["wx"]["approved"] is True


def test_settings_page_has_the_flow_tab_and_hidden_steps_check_the_switch() -> None:
    static = Path(__file__).resolve().parents[1] / "src/content_studio/static"
    html = (static / "index.html").read_text(encoding="utf-8")
    assert 'data-set="flow"' in html and 'data-set-tab="flow"' in html and 'id="flowRows"' in html
    app_js = (static / "app.js").read_text(encoding="utf-8")
    assert "'flow'" in app_js and "components_off" in app_js
    for key in edition.SWITCHES:
        assert f"['{key}'," in app_js, key  # 每个能开关的组件页面上都有一行
    video = (static / "video.js").read_text(encoding="utf-8")
    assert "featureOn('qa')" in video and "featureOn('coupon')" in video
