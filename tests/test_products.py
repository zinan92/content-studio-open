"""作品（10/7 作者）：做过的产品每个一页截图。有网址的每天截一次，没网址的（小程序）传截图；清单在本机，不写死。"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_studio.web import STATIC_DIR
from content_studio.extras.products import products
from content_studio.extras.portal import portal
from tests.test_web import client  # noqa: F401

PNG = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture(autouse=True)
def _home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))


def fake_capture(url: str, folder: Path, variants: tuple[str, ...]) -> None:
    for v in variants:
        (folder / f"{v}.png").write_bytes(PNG)


def test_a_new_install_has_no_products_and_the_list_is_kept_in_order() -> None:
    assert products.items() == [] and products.view() == {"products": [], "product": None}
    a = products.save({"name": "天机", "for": "玄学博主", "url": "tianji.example.com", "views": ["mobile", "desktop"]})
    b = products.save({"name": "轻练", "for": "健身教练", "url": "", "views": ["mobile"]})
    assert (a["key"], b["key"]) == ("p1", "p2")
    assert a["url"] == "https://tianji.example.com" and a["views"] == ["desktop", "mobile"]
    assert [r["name"] for r in products.items()] == ["天机", "轻练"]
    products.save({**b, "name": "轻练 · 教练版"}, "p2")
    products.remove("p1")
    assert [(r["key"], r["name"]) for r in products.items()] == [("p2", "轻练 · 教练版")]
    assert products.save({"name": "交易台"})["key"] == "p3"  # 拿掉的编号不复用，旧文件夹不会串
    with pytest.raises(products.ProductError, match="名字"):
        products.save({"name": "  "})
    with pytest.raises(products.ProductError):
        products.remove("p9")


def test_url_products_are_captured_once_a_day_only_in_the_chosen_views() -> None:
    products.save({"name": "交易台", "url": "http://127.0.0.1:8790/trade", "views": ["desktop"]})
    calls = []
    kw = {"capture": lambda u, f, v: (calls.append((u, v)), fake_capture(u, f, v)), "background": False}
    assert products.start("p1", **kw) is True
    assert products.start("p1", **kw) is False  # 今天截过了
    assert products.start("p1", force=True, **kw) is True  # 他点了「重新截」
    products.save({"name": "交易台", "url": "http://127.0.0.1:8790/trade", "views": ["desktop", "mobile"]}, "p1")
    assert products.start("p1", **kw) is True  # 截哪几种换了
    assert [v for _, v in calls] == [("desktop",), ("desktop",), ("desktop", "mobile")]
    assert products.view("p1")["product"]["shot"]["variants"] == ["desktop", "mobile"]
    products.save({"name": "交易台", "url": "http://127.0.0.1:8790/trade", "views": ["desktop"]}, "p1")
    products.run_once("p1", capture=fake_capture)
    assert products.view("p1")["product"]["shot"]["variants"] == ["desktop"]  # 不再截的那种不留旧图


def test_products_without_a_url_are_never_captured_and_failures_are_shown() -> None:
    products.save({"name": "轻练"})
    assert products.start("p1", capture=fake_capture, background=False) is False
    products.save({"name": "天机", "url": "https://tianji.example.com"})

    def boom(url: str, folder: Path, variants: tuple[str, ...]) -> None:
        raise portal.PortalError("打不开 https://tianji.example.com：timeout")

    assert products.start("p2", capture=boom, background=False) is True
    assert products.view("p2")["product"]["shot"]["error"].startswith("打不开")
    assert products.start("p2", capture=boom, background=False) is False  # 不自动重试，等他点


def test_history_is_kept_for_thirty_days() -> None:
    products.save({"name": "天机", "url": "https://tianji.example.com"})
    for day in ("2026-08-01", "2026-09-20", "2026-10-07"):
        products.run_once("p1", capture=fake_capture, today=day)
    assert products.days("p1") == ["2026-10-07", "2026-09-20"]
    assert products.view("p1", "2026-09-20")["product"]["shot"]["day"] == "2026-09-20"


def test_uploads_are_images_only_named_safely_and_removable() -> None:
    products.save({"name": "知识星球小程序"})
    assert products.add_upload("p1", "01-home.png", PNG) == "01-home.png"
    assert products.add_upload("p1", "01-home.png", PNG) == "01-home-2.png"
    assert products.add_upload("p1", "../../2 公告 · 置顶?.JPG", PNG) == "2 公告 · 置顶.jpg"
    assert products.uploads("p1") == ["01-home-2.png", "01-home.png", "2 公告 · 置顶.jpg"]
    with pytest.raises(products.ProductError, match="图片"):
        products.add_upload("p1", "notes.pdf", PNG)
    with pytest.raises(products.ProductError, match="空"):
        products.add_upload("p1", "a.png", b"")
    assert products.upload_path("p1", "../list.json") is None
    products.remove_upload("p1", "01-home-2.png")
    assert products.uploads("p1") == ["01-home.png", "2 公告 · 置顶.jpg"]


def test_api_lists_adds_uploads_and_serves(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(products, "start", lambda key, **kw: False)  # 测试里不开浏览器
    assert client.get("/api/products").json() == {"products": [], "product": None}
    d = client.post("/api/products", json={"name": "天机", "for": "玄学博主", "url": "https://tianji.example.com"}).json()
    assert d["product"]["key"] == "p1" and d["product"]["uploads"] == []
    assert client.post("/api/products", json={"name": ""}).status_code == 400
    client.post("/api/products", json={"name": "轻练", "views": ["mobile"]})
    up = client.post("/api/products/p2/uploads", files=[("file", ("today.png", PNG, "image/png")), ("file", ("plan.png", PNG, "image/png"))])
    assert up.status_code == 200 and up.json()["product"]["uploads"] == ["plan.png", "today.png"]
    assert client.post("/api/products/p2/uploads", files=[("file", ("x.txt", b"hi", "text/plain"))]).status_code == 400
    img = client.get("/api/products/p2/uploads/today.png")
    assert img.status_code == 200 and img.content == PNG
    assert client.get("/api/products/p2/uploads/..%2Flist.json").status_code == 404
    assert client.post("/api/products/p2/refresh").status_code == 400  # 没网址
    products.run_once("p1", capture=fake_capture, today="2026-10-07")
    assert client.get("/api/products/p1/shot/2026-10-07/desktop.png").content == PNG
    assert client.get("/api/products/p1/shot/2026-10-07/tablet.png").status_code == 404
    assert client.get("/api/products?key=p2").json()["product"]["name"] == "轻练"
    assert client.get("/api/products?key=nope").json()["product"]["key"] == "p1"  # 认不出就看第一个
    assert client.delete("/api/products/p2/uploads/today.png").json()["product"]["uploads"] == ["plan.png"]
    assert [r["key"] for r in client.delete("/api/products/p1").json()["products"]] == ["p2"]


def test_each_product_keeps_its_sales_fields_cleaned() -> None:
    """10/9 变现流程板：每个产品一页六段——报价、收款、流量入口、投放都存在产品清单里，页面上改。"""
    row = products.save({"name": "天机", "status": "live", "price": "全文 ¥19.9", "pay_channel": "微信支付", "pay_link": "pay.example.com/t",
                         "landing": "example.com/products/tianji", "keyword": "天机", "ad_plan": "先不投", "ad_budget": 500})
    assert (row["status"], row["price"], row["pay_channel"], row["keyword"], row["ad_plan"], row["ad_budget"]) == ("live", "全文 ¥19.9", "微信支付", "天机", "先不投", 500)
    assert row["pay_link"] == "https://pay.example.com/t" and row["landing"] == "https://example.com/products/tianji"
    bad = products.save({"name": "轻练", "status": "whatever", "ad_budget": -3})
    assert bad["status"] == "" and bad["ad_budget"] == 0 and bad["price"] == ""


def test_a_product_page_shows_the_money_it_brought_in(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import date

    monkeypatch.setattr(products, "start", lambda key, **kw: False)
    client.post("/api/products", json={"name": "天机"})
    client.post("/api/products", json={"name": "轻练"})
    m0 = client.get("/api/products?key=p1").json()["product"]["money"]
    assert (m0["month"], m0["count"], m0["last"]) == (0, 0, None)
    assert len(m0["weeks"]) == 4 and all(w["paid"] == 0 for w in m0["weeks"])
    today = date.today().isoformat()
    client.post("/api/revenue", json={"amount": 19.9, "source": "p1", "day": today, "note": "全文"})
    client.post("/api/revenue", json={"amount": 1000, "source": "consult", "day": today})
    m = client.get("/api/products?key=p1").json()["product"]["money"]
    assert m["month"] == 19.9 and m["count"] == 1 and m["last"]["note"] == "全文"
    assert m["weeks"][-1] == {"week": m["weeks"][-1]["week"], "paid": 1, "amount": 19.9}  # 漏斗按周：这一周 1 笔付款


def test_listing_for_the_rail_does_not_start_a_capture(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    started = []
    monkeypatch.setattr(products, "start", lambda key, **kw: started.append(key) or False)
    client.post("/api/products", json={"name": "天机", "url": "https://tianji.example.com"})
    started.clear()
    assert [r["name"] for r in client.get("/api/products?list=1").json()["products"]] == ["天机"]
    assert started == []


def test_products_have_their_own_rail_group_built_from_the_list() -> None:
    """10/9 作者：「作品」一页五个子页签拆开，每个产品一个 tab。清单在本机，左栏由 products.js 照清单画。"""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    # 10/9：分组标题能点开收起（data-rail-fold），产品列表在它下面；10/12 作者：并进「产品类」那一组
    group = html[html.index('data-rail-fold-body="more"'):]
    assert group.index('id="railProducts"') < group.index('</nav>')
    assert 'data-view="products"' not in html and '<script src="/static/products.js"></script>' in html
    js = (STATIC_DIR / "products.js").read_text(encoding="utf-8")
    assert "window.paintProductRail" in js and "/api/products?list=1" in js and "pd-tabs" not in js
    for title in ("产品", "报价", "收款", "流量入口", "投放", "漏斗"):
        assert f"'{title}'" in js, title  # 每页六段，顺序照变现流程板


def test_a_content_can_carry_one_product_and_drops_it_when_untagged(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """#590：「标题和封面」① 里选这条带哪个产品；产品页「流量入口」列出带它的内容。"""
    monkeypatch.setattr(products, "start", lambda key, **kw: False)
    client.post("/api/products", json={"name": "天机", "keyword": "天机"})
    tid = client.post("/api/topics", json={"title": "算命网站一周收了多少"}).json()["id"]
    got = client.get(f"/api/topics/{tid}/product").json()
    assert got["product"] is None and [r["name"] for r in got["products"]] == ["天机"]
    assert client.put(f"/api/topics/{tid}/product", json={"product": "p1"}).json()["product"] == "p1"
    assert products.product_for(tid)["name"] == "天机"
    page = client.get("/api/products?key=p1").json()["product"]
    assert page["content"] == [{"topic_id": tid, "title": "算命网站一周收了多少"}]
    assert client.put(f"/api/topics/{tid}/product", json={"product": "p9"}).status_code == 400
    assert client.put(f"/api/topics/{tid}/product", json={"product": None}).json()["product"] is None
    assert products.product_for(tid) is None and client.get("/api/products?key=p1").json()["product"]["content"] == []
