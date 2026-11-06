"""pytest 插件：把时钟往前拨 TIMESHIFT_DAYS 天，找出「到某一天才会失败」的测试。

    PYTHONPATH=tools TIMESHIFT_DAYS=365 python3 -m pytest -q -p timeshift

写死日期的夹具（比如把发布时间钉在某个时间戳）会随真实时间推移掉出 7 天 / 30 天 /
90 天各种窗口，到某一天整批测试无缘无故变红。2026-09-21 就发生过一次：报告夹具的
generated_at 写死在 09-14，而超过 7 天没读的报告读取时自动归档，正好第 7 天炸了。

已知局限：它伪造不了文件 mtime。凡是靠 `vault.inbox`（比较文件修改时间）的测试，在
拨快之后一定失败，那是这个工具的假阳性，不是产品 bug。判断真假的办法是看失败原因里
有没有写死的日期字面量。
"""
import datetime as _dt
import importlib
import os
import pkgutil

OFFSET = _dt.timedelta(days=int(os.environ.get("TIMESHIFT_DAYS", "0")))


class ShiftedDateTime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return _dt.datetime.now(tz) + OFFSET

    @classmethod
    def utcnow(cls):
        return _dt.datetime.utcnow() + OFFSET

    @classmethod
    def today(cls):
        return _dt.datetime.today() + OFFSET


class ShiftedDate(_dt.date):
    @classmethod
    def today(cls):
        return _dt.date.today() + OFFSET


def pytest_configure(config):
    if not OFFSET:
        return
    import content_studio

    patched = []
    for info in pkgutil.iter_modules(content_studio.__path__):
        mod = importlib.import_module(f"content_studio.{info.name}")
        if getattr(mod, "datetime", None) is _dt.datetime:
            mod.datetime = ShiftedDateTime
            patched.append(f"{info.name}.datetime")
        if getattr(mod, "date", None) is _dt.date:
            mod.date = ShiftedDate
            patched.append(f"{info.name}.date")
    print(f"\n[timeshift] +{OFFSET.days}d on {len(patched)} names")
