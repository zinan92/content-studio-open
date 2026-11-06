"""iCloud 占位文件和同步目录的识别。

9/22 的项目建在 ~/Documents/Codex/Workspaces/ 下，那里开着 iCloud「桌面与文稿」同步。
系统空间紧的时候会把视频卸载成占位文件（dataless）：文件名、大小都还在，本地没有数据。
ffprobe 读到的是空壳，报 `moov atom not found`——看起来像文件坏了，其实只是没下载。
那天因为这个前后耽误了两个多小时，还让人误判成了文件损坏。

两道防线：项目根目录不许在 iCloud 同步范围里；读媒体之前先认出占位文件，
报「没下载到本地」而不是报格式错误。
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
from pathlib import Path
import stat

PROVIDER_XATTR = "com.apple.file-provider-domain-id"
MOBILE_DOCUMENTS = Path("~/Library/Mobile Documents").expanduser()


class NotLocalError(OSError):
    """文件在 iCloud 里但没下载到本地。消息是给人看的。"""


def is_dataless(path: Path) -> bool:
    """占位文件：st_flags 带 SF_DATALESS。读不到 stat 就当不是。"""
    try:
        return bool(os.stat(path).st_flags & stat.SF_DATALESS)
    except (OSError, AttributeError):
        return False


def _libc() -> ctypes.CDLL | None:
    name = ctypes.util.find_library("c")
    return ctypes.CDLL(name, use_errno=True) if name else None


def _has_xattr(path: Path, name: str) -> bool:
    lib = _libc()
    if lib is None or not hasattr(lib, "getxattr"):
        return False
    # macOS: ssize_t getxattr(path, name, value, size, position, options)
    size = lib.getxattr(os.fsencode(str(path)), name.encode(), None, ctypes.c_size_t(0), ctypes.c_uint32(0), ctypes.c_int(0))
    return size >= 0


def icloud_owner(path: Path, *, mobile: Path = MOBILE_DOCUMENTS) -> Path | None:
    """这个路径落在哪个 iCloud 同步目录里；不在就返回 None。

    两种情况：在 ~/Library/Mobile Documents 下（iCloud Drive 本体），或者某一级祖先
    目录带 file-provider 的 xattr（「桌面与文稿」同步开着时，~/Documents 就带它）。
    """
    p = Path(path).expanduser()
    try:
        p = p.resolve()
        mobile = mobile.resolve()
    except OSError:
        pass
    for candidate in (p, *p.parents):
        if candidate == mobile:
            return mobile
        if candidate.exists() and _has_xattr(candidate, PROVIDER_XATTR):
            return candidate
    return None


def refuse_synced_root(root: Path) -> None:
    owner = icloud_owner(root)
    if owner is not None:
        raise ValueError(
            f"视频项目目录 {root} 在 iCloud 同步范围里（{owner}）。"
            "系统空间紧时会把视频卸载成占位文件，读到的是空壳。换到外置盘，比如 /Volumes/Phone SSD/视频/exports。"
        )


def ensure_local(path: Path) -> Path:
    if is_dataless(path):
        raise NotLocalError(
            f"{Path(path).name} 在 iCloud 里没下载到本地（占位文件）。"
            "在访达里右键「立即下载」，或者把项目挪到外置盘上。"
        )
    return path
