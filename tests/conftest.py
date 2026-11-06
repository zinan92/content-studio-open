"""Shared fixtures."""

import os as _os
import tempfile as _tempfile

import pytest as _pytest

# 测试别读本机的 park-writing（写作规则 skill）：一律当没装，要测的自己建临时 skill。
_os.environ["CONTENT_STUDIO_WRITING_SKILL"] = "off"
# 发布完成后会在浏览器里打开平台页面；测试里不要真的打开。
_os.environ["CONTENT_STUDIO_NO_OPEN"] = "1"
# 本机 profile.yaml 里的可选配置（conf.py）别漏进测试：测试只看默认值和各自显式传的配置。
_os.environ["CONTENT_STUDIO_SKIP_PROFILE_ENV"] = "1"
# 写完文章会接着用 Codex 配图；测试里不要真的去画。
_os.environ["CONTENT_STUDIO_NO_ILLUSTRATE"] = "1"
# 10/19 起视频一进项目就自动跑本机 whisper；测试里的视频都是假的，别真去转写（要测的自己 delenv + 换掉 koubo.transcribe）。
_os.environ["CONTENT_STUDIO_NO_AUTO_TRANSCRIBE"] = "1"
# 切 Hook 后会用本机 mlx-whisper 重新听首尾字；测试里一律不加载模型（要测的自己传假的 asr）。
_os.environ["CONTENT_STUDIO_NO_HOOK_ASR"] = "1"
# 10/9 出过事：一个测试直接调了发 X 的函数，本机 ~/.config/content-studio/secrets.yaml 里有真密钥，真发出去了一条。
# 测试一律指到一个不存在的密钥文件：任何发帖都只会报「缺密钥」，碰不到他的账号。
_os.environ["CONTENT_STUDIO_SECRETS"] = _os.path.join(_tempfile.mkdtemp(prefix="cs-secrets-"), "none.yaml")
# 个人形象文件夹默认是 作者 的 ~/.config/park-visual；测试里指到一个空的临时目录，别读他的角色、别往他的形象库里存图。
_os.environ["CONTENT_STUDIO_PERSONA"] = _tempfile.mkdtemp(prefix="cs-persona-")


@_pytest.fixture(autouse=True)
def _reset_vault_sources():
    """vault.INBOX_SOURCES / DAILY_SOURCES 是模块全局，profile.yaml 会重写它们。
    一个测试配过之后不复位，下一个没建 app 的测试读到的就是缩过的来源表，
    _allowed_folders() 的白名单跟着缩，读笔记直接被拒——test_writer 就是这么挂的。"""
    from content_studio import vault

    yield
    vault.configure(None)

# 所有新增后台读数默认落在测试目录，绝不接触本机工作台产物。
_test_home = _tempfile.TemporaryDirectory(prefix="cs-test-home-")
_os.environ["CONTENT_STUDIO_HOME"] = _test_home.name
_os.environ["CONTENT_STUDIO_CONSULTS"] = _os.path.join(_test_home.name, "consults")
_os.environ["CONTENT_STUDIO_PORTRAITS"] = _os.path.join(_test_home.name, "portraits")
_os.environ["CONTENT_STUDIO_WORLDVIEW"] = _os.path.join(_test_home.name, "worldview.md")


@_pytest.fixture(autouse=True)
def _block_personal_data_and_real_ai(monkeypatch, tmp_path):
    """误漏注入时直接失败，不读真实配置，也不启动真实 Codex。"""
    import builtins
    import io
    from pathlib import Path
    import subprocess

    forbidden = [Path.home() / '.config/content-studio', Path.home() / 'notes']
    original_open, original_io_open = builtins.open, io.open
    original_popen = subprocess.Popen
    from content_studio import skills
    from content_studio.store import DEFAULT_SETTINGS
    test_roots = (tmp_path / "skills",)
    original_roots = skills.SKILL_ROOTS
    for fn in (skills.load_skills, skills.safe_doc_path, skills.doc_roots):
        monkeypatch.setattr(fn, "__defaults__", tuple(test_roots if arg == original_roots else arg for arg in fn.__defaults__))
    monkeypatch.setattr(skills.read_doc, "__kwdefaults__", {**skills.read_doc.__kwdefaults__, "roots": test_roots})
    monkeypatch.setattr(skills, "SKILL_ROOTS", test_roots)
    monkeypatch.setitem(DEFAULT_SETTINGS, "park_writing_skill", str(tmp_path / "skills/park-writing/SKILL.md"))
    monkeypatch.setenv("CONTENT_STUDIO_QA_GUIDE", str(tmp_path / "skills/qa/SKILL.md"))

    def checked(opener):
        def open_file(file, *args, **kwargs):
            if isinstance(file, (str, _os.PathLike)):
                path = Path(file).expanduser().resolve()
                if any(path == root or root in path.parents for root in forbidden):
                    raise AssertionError(f"测试禁止读写真实个人目录：{path}")
            return opener(file, *args, **kwargs)
        return open_file

    def popen(args, *a, **kw):
        argv = args if isinstance(args, (list, tuple)) else str(args).split()
        if argv and Path(str(argv[0])).name in {'codex', 'claude'} and not Path(str(argv[0])).resolve().is_relative_to(tmp_path.resolve()):
            raise AssertionError('测试必须注入假 AI runner')
        return original_popen(args, *a, **kw)

    monkeypatch.setattr(builtins, 'open', checked(original_open))
    monkeypatch.setattr(io, 'open', checked(original_io_open))
    monkeypatch.setattr(subprocess, 'Popen', popen)
