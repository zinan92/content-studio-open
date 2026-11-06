#!/bin/zsh
# 内容工作台 · 在客户的 Mac 上装一遍（作者 到场或远程时跑）
#
#   ./install-mac.sh --check      只做装机前检查，什么都不装
#   ./install-mac.sh              检查通过后全部装好
#   ./install-mac.sh --trial      装成试用版（profile.yaml 写 edition: trial，哪些不出现见 src/content_studio/edition.py）
#   一行装：curl -fsSL …/install-mac.sh | zsh -s -- --trial
#
# 装什么：Python / Node / ffmpeg（Homebrew）→ 工作台代码（main 分支）→ 独立的虚拟环境和依赖
# → 转写模型、浏览器组件 → deploy.json 里的依赖仓库 → profile.yaml → 开机自启的后台服务。
# 不会动这台电脑上已有的任何工作台安装；已经存在的目录只提示、不覆盖。
# 装完照着 Obsidian 里 009_product-os/内容工作台/装机清单.md 做剩下的（买 key、登录平台、填配置）。
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/zinan92/content-studio-open.git}"
APP_DIR="${APP_DIR:-$HOME/work/content-studio}"
LABEL="${LABEL:-com.content-studio.app}"
PORT="${PORT:-8780}"
WANT="${CONTENT_STUDIO_BRANCH:-main}"
PREFLIGHT_TMP=""
trap '[[ -z "$PREFLIGHT_TMP" ]] || rm -rf "$PREFLIGHT_TMP"' EXIT
HERE="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd || echo "")"
CHECK_ONLY=""; EDITION="${CONTENT_STUDIO_EDITION:-full}"
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --trial) EDITION=trial ;;
    *) print "不认识的参数：$arg（只有 --check、--trial）"; exit 2 ;;
  esac
done
[[ "$EDITION" == trial ]] && EDITION_LABEL="试用版" || EDITION_LABEL="完整版"

say() { print -P "%B$1%b"; }
note() { print "  $1"; }

preflight() {
  local src="$HERE/src/content_studio/preflight.py"
  [[ -f "$src" ]] || src="$APP_DIR/src/content_studio/preflight.py"
  if [[ ! -f "$src" ]]; then
    PREFLIGHT_TMP="$(mktemp -d)"
    src="$PREFLIGHT_TMP/preflight.py"
    curl -fsSL "https://raw.githubusercontent.com/zinan92/content-studio-open/$WANT/src/content_studio/preflight.py" -o "$src"
  fi
  /usr/bin/python3 "$src"
}

if [[ -n "$CHECK_ONLY" ]]; then
  rc=0; preflight || rc=$?
  print "\n会装到：$APP_DIR（分支 $WANT，$EDITION_LABEL），服务名 $LABEL，端口 $PORT"
  exit $rc
fi

if [[ -e "$APP_DIR" ]]; then
  print "已经有 $APP_DIR，不覆盖。已有工作台请在设置 → 版本里检查更新；彩排请使用另一台 Mac 或指定空的 APP_DIR。"
  exit 1
fi

say "1/8 装机前检查"
preflight || { print "硬件或系统不够，停。"; exit 1; }

say "2/8 基础工具（Homebrew）"
command -v brew >/dev/null || { print "没有 Homebrew：先装 https://brew.sh ，再重跑这个脚本。"; exit 1; }
for f in python@3.12 node ffmpeg git; do brew list --versions "$f" >/dev/null 2>&1 || brew install "$f"; done
PY="$(brew --prefix)/bin/python3.12"

say "3/8 工作台代码"
mkdir -p "$(dirname "$APP_DIR")"
git ls-remote --exit-code --heads "$REPO_URL" "$WANT" >/dev/null 2>&1 || {
  print "找不到 $WANT 分支或连不上仓库，停。客户版本要先在彩排机验收，再由 作者 发布到 stable。"
  exit 1
}
git clone --branch "$WANT" "$REPO_URL" "$APP_DIR"
BRANCH="$(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD)"

say "4/8 独立的 Python 环境和依赖"
[[ -d "$APP_DIR/.venv" ]] || "$PY" -m venv "$APP_DIR/.venv"
touch "$APP_DIR/.venv/.content-studio-managed"   # 「检查更新」认这个标记：依赖变了只装在这里
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -e "$APP_DIR" mlx-whisper playwright huggingface_hub

say "5/8 转写模型、浏览器组件（约 2GB，第一次要等一会儿）"
"$APP_DIR/.venv/bin/python" -m playwright install chromium
"$APP_DIR/.venv/bin/python" -c "from huggingface_hub import snapshot_download; snapshot_download('mlx-community/whisper-large-v3-turbo')"

say "6/8 依赖仓库（deploy.json）"
"$APP_DIR/.venv/bin/python" - "$APP_DIR/deploy.json" <<'PY'
import json, os, subprocess, sys
for d in json.load(open(sys.argv[1]))["deps"]:
    path = os.path.expanduser(d["path"])
    if os.path.exists(path):
        print(f"  已有  {d['name']}（{d['feature']}）"); continue
    if not d["repo"]:
        print(f"  跳过  {d['name']}：还没有能拉的地方，要 作者 手动拷（{d['feature']}）"); continue
    if not d["required"] and d["access"] == "private":
        print(f"  跳过  {d['name']}：可选且私有（{d['feature']}）"); continue
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ok = subprocess.run(["git", "clone", "--quiet", "--branch", d["ref"], d["repo"], path]).returncode == 0
    print(f"  {'装好' if ok else '失败'}  {d['name']}" + ("" if ok else f"：{'私有仓库，要先 gh auth login 或让 作者 给权限' if d['access'] == 'private' else '拉不下来'}"))
    for link in d.get("links") or []:
        at = os.path.expanduser(link["at"])
        if ok and not os.path.lexists(at):
            os.makedirs(os.path.dirname(at), exist_ok=True)
            os.symlink(os.path.join(path, link["to"]), at)
            print(f"        链接 {link['at']}")
PY

say "7/8 配置文件"
if [[ -f "$APP_DIR/profile.yaml" ]]; then
  note "已经有 profile.yaml，不覆盖"
else
  cp "$APP_DIR/profile.example.yaml" "$APP_DIR/profile.yaml"
  cat >> "$APP_DIR/profile.yaml" <<YAML

# ─── 装机脚本写的 ───
edition: $EDITION
update:
  branch: $BRANCH
service:
  label: $LABEL
  restart: ~/.local/bin/content-studio-restart
YAML
  note "profile.yaml 建好了，照 配置单.md 填客户自己的值"
fi

say "8/8 开机自启的后台服务"
mkdir -p "$HOME/.local/bin" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/ContentStudio"
mkdir -p "$HOME/.config/content-studio/studio/logs"
sed "s/com.content-studio.app/$LABEL/" "$APP_DIR/scripts/content-studio-restart" > "$HOME/.local/bin/content-studio-restart"
chmod +x "$HOME/.local/bin/content-studio-restart"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$APP_DIR/.venv/bin/python</string><string>-m</string><string>content_studio</string>
    <string>serve</string><string>--port</string><string>$PORT</string>
  </array>
  <key>WorkingDirectory</key><string>$APP_DIR</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$APP_DIR/.venv/bin:$(brew --prefix)/bin:/usr/bin:/bin:$HOME/.local/bin</string>
    <key>HOME</key><string>$HOME</string>
    <key>USER</key><string>$USER</string>
    <key>LOGNAME</key><string>$USER</string>
    <key>CONTENT_STUDIO_SERVICE_LABEL</key><string>$LABEL</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/ContentStudio/content-studio.stdout.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/ContentStudio/content-studio.stderr.log</string>
</dict></plist>
PLIST
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

# 生成每日同步配置；走完「开始用」和账号验收后，由安装负责人按交接清单启用。
SYNC_PLIST="$HOME/Library/LaunchAgents/com.content-studio.daily-sync.plist"
"$APP_DIR/.venv/bin/python" -m content_studio write-schedule --output "$SYNC_PLIST" >/dev/null
note "每日同步配置已生成，账号验收后启用：launchctl bootstrap gui/\$(id -u) $SYNC_PLIST"

say "装好了：打开 http://127.0.0.1:$PORT"
"$APP_DIR/.venv/bin/python" -m content_studio check || true
note "装完在浏览器里走「开始用」三步，然后终端里：$APP_DIR/.venv/bin/content-studio acceptance"
print "\n接下来照 装机清单.md：买 DeepSeek / MiniMax key、在 Chrome 里登录各平台、填 profile.yaml。"
