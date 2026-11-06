"""作品：做过的产品每个一页截图（10/7），挂在左栏「门户」下面。试用版没有这一块。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（features/__init__.py 当场核对）
NEEDS: tuple[str, ...] = ("hooks", "store",)
PROVIDES: tuple[str, ...] = ()


def register(app: Any, ctx: Any) -> None:
    store = ctx.store

    def _rows() -> list[dict[str, Any]]:
        from . import products

        return products.items()

    ctx.hooks["product_rows"] = _rows  # 今天页「记一笔」的来源：咨询 + 每个产品

    def _product_for(topic_id: int) -> dict[str, Any] | None:
        from . import products

        return products.product_for(topic_id)

    ctx.hooks["product_for_topic"] = _product_for  # 发出去时描述末尾加这条带的产品（#590）

    # ---------------- 作品（10/7 作者：做过的产品每个一页截图，跟 GitHub、网站一起放在「门户」下面） ----------------
    def _product_call(fn: Callable[[], Any]) -> Any:
        from . import products

        try:
            return fn()
        except products.ProductError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    def _with_money(out: dict[str, Any]) -> dict[str, Any]:
        """这个产品这个月记了几笔、多少钱、最近一笔，和最近 4 周每周的付款笔数和收入（收入账本里 source 是它的）。"""
        p = out.get("product")
        if p:
            from . import products

            # 流量入口：哪几条内容带了它（#590）；各带来多少人，页面拿汇总表的触达对上
            ids = [tid for tid, k in products.content_tags().items() if k == p["key"]]
            titles = {t["id"]: t["title"] for t in store.topics(include_archived=True) if t["id"] in ids}
            p["content"] = [{"topic_id": tid, "title": titles[tid]} for tid in sorted(ids, reverse=True) if tid in titles]
            today = date.today()
            month = today.replace(day=1).isoformat()
            monday = today - timedelta(days=today.weekday())
            starts = [monday - timedelta(weeks=i) for i in range(3, -1, -1)]
            since = min(month, starts[0].isoformat())
            mine = [r for r in store.revenue(since) if r["source"] == p["key"]]
            rows = [r for r in mine if r["day"] >= month]
            weeks = []
            for start in starts:
                end = (start + timedelta(days=7)).isoformat()
                got = [r for r in mine if start.isoformat() <= r["day"] < end]
                weeks.append({"week": start.isoformat(), "paid": len(got), "amount": round(sum(r["amount"] for r in got), 2)})
            p["money"] = {"month": round(sum(r["amount"] for r in rows), 2), "count": len(rows), "last": rows[-1] if rows else None,
                          "weeks": weeks}
        return out

    @app.get("/api/topics/{topic_id}/product")
    def get_topic_product(topic_id: int) -> dict[str, Any]:
        """「标题和封面」①：这条带哪个产品，和能选的产品。"""
        from . import products

        store.topic(topic_id)
        return {"product": products.content_tags().get(topic_id), "products": [{"key": r["key"], "name": r["name"]} for r in products.items()]}

    @app.put("/api/topics/{topic_id}/product")
    def put_topic_product(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        from . import products

        topic = store.topic(topic_id)
        key = _product_call(lambda: products.tag_content(topic_id, str(body.get("product") or "").strip() or None))
        name = next((r["name"] for r in products.items() if r["key"] == key), None)
        store.log_event("products", f"「{topic['title'][:20]}」{'带上「' + name + '」' if name else '不带产品'}")
        return get_topic_product(topic_id)

    @app.get("/api/products")
    def get_products(key: str | None = None, day: str | None = None, list: bool = False) -> dict[str, Any]:  # noqa: A002
        """打开哪一个、就在后台给它截今天那一次（有网址的）；前端看到 running 过一会儿再问。list=1 是左栏要清单，不截。"""
        from . import products

        rows = products.items()
        if list:
            return {"products": rows, "product": None}
        pick = key if any(r["key"] == key for r in rows) else (rows[0]["key"] if rows else None)
        if pick and day is None:
            products.start(pick)
        return _with_money(products.view(pick, day))

    @app.post("/api/products")
    def add_product(body: dict[str, Any]) -> dict[str, Any]:
        from . import products

        row = _product_call(lambda: products.save(body))
        store.log_event("products", f"作品：加了「{row['name']}」")
        return _with_money(products.view(row["key"]))

    @app.put("/api/products/{key}")
    def edit_product(key: str, body: dict[str, Any]) -> dict[str, Any]:
        from . import products

        row = _product_call(lambda: products.save(body, key))
        products.start(key)
        return _with_money(products.view(row["key"]))

    @app.delete("/api/products/{key}")
    def delete_product(key: str) -> dict[str, Any]:
        from . import products

        _product_call(lambda: products.remove(key))
        return products.view()

    @app.post("/api/products/{key}/refresh")
    def refresh_product(key: str) -> dict[str, Any]:
        from . import products

        row = _product_call(lambda: products.get(key))
        if not row["url"]:
            raise HTTPException(status_code=400, detail="这个作品没填网址，传截图就行")
        products.start(key, force=True)
        return _with_money(products.view(key))

    @app.post("/api/products/{key}/uploads")
    async def upload_product_shot(key: str, request: Request) -> dict[str, Any]:
        from . import products

        form = await request.form()
        files = [f for f in form.getlist("file") if getattr(f, "filename", "")]
        if not files:
            raise HTTPException(status_code=400, detail="没收到图")
        for f in files:
            data = await f.read()
            _product_call(lambda f=f, data=data: products.add_upload(key, f.filename, data))
        return _with_money(products.view(key))

    @app.delete("/api/products/{key}/uploads/{name}")
    def delete_product_shot(key: str, name: str) -> dict[str, Any]:
        from . import products

        _product_call(lambda: products.remove_upload(key, name))
        return _with_money(products.view(key))

    @app.get("/api/products/{key}/uploads/{name}")
    def product_upload_file(key: str, name: str) -> FileResponse:
        from . import products

        path = products.upload_path(key, name)
        if path is None:
            raise HTTPException(status_code=404, detail="没有这张图")
        return FileResponse(path)

    @app.get("/api/products/{key}/shot/{day}/{variant}.png")
    def product_shot(key: str, day: str, variant: str) -> FileResponse:
        from . import products

        path = products.shot_path(key, day, variant)
        if path is None:
            raise HTTPException(status_code=404, detail="没有这张截图")
        return FileResponse(path, media_type="image/png")
