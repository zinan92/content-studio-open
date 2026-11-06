"""试用版开关（10/8 作者 批准，#526）：同一套代码，profile.yaml 写一行 `edition: trial`，下面这些就不出现。

不另开分支：完整版和试用版的差别只在这一张表里。前端从 /api/state 拿到「关了哪些」，带 data-feature 的入口自己藏；
后端在中间件里按 routes 拒掉对应接口，后台循环开工前问一句 on()。没写、写错、写 full 都当完整版——作者自己那台不受影响。


10/9 作者：流程是他自己这一套，固定不让调；用户能做的只是开关其中的组件（SWITCHES）。用户关掉的存在设置
components_off 里，和版本砍掉的合在一起给前端藏入口、给后台循环和流水线跳步；但接口不拦（blocked 只看版本）：
关掉以前做出来的付息稿、插图照样打得开，开着的页面也不会突然报错。
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class Feature:
    label: str
    routes: tuple[str, ...] = ()   # 正则，匹配 /api/ 后面的路径；试用版里这些接口一律 404


FEATURES: dict[str, Feature] = {
    # 左栏整页
    "others": Feature("其他三个（B 站 · YouTube · 公众号）", (r"platform/others(/|$)",)),
    "portal": Feature("门户 · GitHub 和网站", (r"portal/",)),
    "products": Feature("门户 · 作品", (r"products(/|$)",)),
    "consults": Feature("咨询客户", (r"consults(/|$)", r"clients(/|$)")),
    "team": Feature("AI 团队（Anna / Wendy）", (r"anna(/|$)", r"wendy(/|$)", r"today/review(/|$)")),
    "positioning": Feature("定位页（我是谁 · 找到谁 · 卖什么）", (r"positioning(/|$)", r"persona(/|$)", r"profile(/|$)")),
    # 页面里的一块
    "score": Feature("今天 · 出摊打分和减分"),
    "dailies": Feature("选题 · 日报", (r"vault/dailies$", r"vault/daily/", r"today/dailies$", r"kline/")),
    "series": Feature("写稿 · 系列", (r"series(/|$)",)),
    "motion": Feature("加工中 · 动效", (r"video-v2/", r"topics/\d+/video-project/v2/", r"topics/\d+/motion-plan")),
    "proof": Feature("加工中 · 按论点找证据、证据图", (r"topics/\d+/proof", r"topics/\d+/evidence", r"evidence/")),
    # 补发工作台的「开始」不拦：试用版里它只备上传文件夹（web._bw_run）
    "autopost": Feature("平台页 · 机器代发", (r"topics/\d+/platform/[^/]+/send$", r"topics/\d+/publish-jobs$", r"publish-jobs/")),
    "xline": Feature("X · 每日短帖和「发 X」", (r"xline(/|$)", r"rawtidy(/|$)")),
    "tools": Feature("单点功能", (r"tools(/|$)",)),
    "materials": Feature("素材页（出图 · 风格 · 学一个新的 · 素材卡）", (r"material-agent(/|$)", r"sucai(/|$)")),
    "tree": Feature("知识树 · 内化", (r"tree(/|$)",)),
    "moments": Feature("朋友圈 · X 复刻到小号", (r"moments(/|$)",)),
    # 只藏页签：这是 作者自己的 skill 清单；接口留着，「写文章照哪个 skill」的下拉还要读
    "skills": Feature("设置 · Skills 清单"),
    # 流水线里的一步（10/9）：只给用户开关，试用版不砍
    "qa": Feature("写稿 · 三点评分"),
    "coupon": Feature("写稿 · 密度"),
    "figs": Feature("加工 · 插图"),
}

# 用户在「设置 · 流程」里能开关的组件：流程里的一步，不是整页（10/9）
# 10/20：xline 不再让用户开关——X 每天排帖那套 #711 已经关了，这个键现在管的是「写」里的口播稿和「剪」里的拍后批注，
# 关掉它等于把写稿页拿掉。试用版照样在 EDITIONS 里砍它。
SWITCHES: tuple[str, ...] = ("dailies", "series", "qa", "coupon", "proof", "motion", "figs", "autopost")

EDITIONS: dict[str, frozenset[str]] = {
    "full": frozenset(),
    # 写死成 10/8 那一批：以后加进 FEATURES 的（qa、coupon、figs）不会顺手被试用版砍掉
    "trial": frozenset(("others", "portal", "products", "consults", "team", "positioning", "score", "dailies", "series",
                        "motion", "proof", "autopost", "xline", "skills", "tools", "materials", "tree", "moments")),
}

# 试用版里藏起来的平台：只能靠机器发、或者只在「其他三个」那页里出现的
TRIAL_PLATFORMS_OFF = ("bilibili", "youtube", "wechat_mp")

_COMPILED = {key: tuple(re.compile(p) for p in f.routes) for key, f in FEATURES.items()}


def name(profile: dict[str, Any] | None) -> str:
    raw = str((profile or {}).get("edition") or "").strip().lower()
    return raw if raw in EDITIONS else "full"


def off(profile: dict[str, Any] | None, user_off: Any = ()) -> frozenset[str]:
    """版本砍掉的，加上用户自己关掉的（只认 SWITCHES 里的）。"""
    return EDITIONS[name(profile)] | (frozenset(user_off or ()) & frozenset(SWITCHES))


def on(key: str, profile: dict[str, Any] | None, user_off: Any = ()) -> bool:
    return key not in off(profile, user_off)


def platforms_off(profile: dict[str, Any] | None) -> tuple[str, ...]:
    return TRIAL_PLATFORMS_OFF if "others" in off(profile) else ()


def blocked(path: str, profile: dict[str, Any] | None) -> str | None:
    """这个请求属于哪一项被关掉的功能；没关返回 None。path 是完整路径（/api/...）。"""
    cut = off(profile)  # 只看版本：用户关掉的组件不拦接口
    if not cut or not path.startswith("/api/"):
        return None
    rest = path[len("/api/"):]
    for key in cut:
        if any(p.match(rest) for p in _COMPILED[key]):
            return key
    return None


def view(profile: dict[str, Any] | None, user_off: Any = ()) -> dict[str, Any]:
    """给前端：/api/state.edition。off 是合起来的（featureOn 用）；cut 是这个版本没有的、user_off 是用户关的（流程页分开说）。"""
    return {"name": name(profile), "off": sorted(off(profile, user_off)), "cut": sorted(off(profile)),
            "user_off": sorted(off(profile, user_off) - off(profile)), "switches": list(SWITCHES),
            "platforms_off": list(platforms_off(profile))}
