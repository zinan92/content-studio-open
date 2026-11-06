-- 内容工作台读数：每天早上由 launchd 用 `open` 启动，读小红书数据页的截图。
-- 做成 App 是因为后台进程弹不出「允许控制 Chrome / 录屏」的授权框；App 第一次运行时会问 作者 一次。
-- 先由 App 自己碰一下 Chrome：授权框只会替 App 本身弹出来，替它启动的 Python 弹不出来。
tell application "Google Chrome" to count windows
do shell script "cd ~/work/content-studio && PYTHONPATH=src /usr/local/bin/python3 -m content_studio screen-reach >> ~/.config/content-studio/logs/screen-reach.log 2>&1 || true"
