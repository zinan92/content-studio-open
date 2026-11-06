#!/bin/sh
# 小红书触达的每日读数：装「内容工作台读数」小 App + 每天 9:25 的 launchd 任务。
# 为什么是 App：后台进程弹不出「允许控制 Chrome / 录屏」的授权框，App 可以（见 decision-log）。
# 注意：重建 App 会换签名，macOS 可能要 作者 重新点一次「允许」、重新开一次录屏开关。
#   sh scripts/install-screen-reach.sh            只装定时任务
#   sh scripts/install-screen-reach.sh --rebuild  连 App 一起重建
set -e
APP="$HOME/Applications/内容工作台读数.app"
LABEL=com.content-studio.screen-reach
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
cd "$(dirname "$0")/.."
if [ "$1" = "--rebuild" ] || [ ! -d "$APP" ]; then
  mkdir -p "$HOME/Applications"
  rm -rf "$APP"
  osacompile -o "$APP" scripts/screen-reach-app.applescript
  /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $LABEL" "$APP/Contents/Info.plist" 2>/dev/null || /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string $LABEL" "$APP/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Add :NSAppleEventsUsageDescription string 每天早上打开小红书数据页读播放数" "$APP/Contents/Info.plist" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$APP/Contents/Info.plist" 2>/dev/null || true
  codesign -f -s - "$APP"
fi
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/usr/bin/open</string><string>-g</string><string>$APP</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>25</integer></dict>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "装好了：每天 9:25 读小红书，日志在 ~/.config/content-studio/logs/screen-reach.log"
