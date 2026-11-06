"""Local-first content monitoring and analysis tools."""

__all__ = ["__version__"]
__version__ = "0.1.0"

# profile.yaml 里的可选配置（路径、品牌…）先落成环境变量，各模块导入时就能读到。不填 = 原来的值。
try:
    from . import conf as _conf

    _conf.apply()
except Exception:  # noqa: BLE001 - 配置读不了也要能起来
    pass
