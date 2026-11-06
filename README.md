# 内容工作台 · content-studio-open

一个人的内容生产线，装在自己的 Mac 上：从进来的素材到选题、骨架、口播稿、剪辑、发布，再到看数据、复盘，在同一个页面里走完。

```
in   Obsidian 笔记库 + 你盯的对标账号 + 你自己的抖音、X 等账号
out  选题池、加工看板、拍摄骨架、标题封面、剪辑进度、各平台发布包、发出后的数据和复盘

fail Obsidian 路径不存在      → 页面提示去设置，其它功能照常
fail 抖音登录过期            → 顶部提示重新导出，不发请求
fail 抖音验证页 / 反作弊      → 立即停止抓取并说明原因，不绕过
fail 本机 AI 没登录          → 任务标失败并写明怎么修，不空转重试
```

它只在本机运行：笔记只读，登录信息和数据不出你的电脑。工作台不替你评论、不替你私信；要发布时，每次都由你确认。

## 适合谁

- 自己做内容、每天要拍或要写的一个人
- 有一台 Apple Silicon Mac，愿意自己装软件、改配置
- 已经在用 Codex 或 Claude Code

不适合：不想装软件、只想打开网页就用的人。工作台不附送 AI 订阅，也不提供安装支持：装和修都交给你自己的 AI。

## 有什么

| 一段 | 做什么 |
|---|---|
| 进项 | 读 Obsidian 里的笔记、收藏、剪藏、日报；对标账号的爆款按「几倍平时」排 |
| 选题 | 选题池、排期、暂缓；三点打分（痛点具象度、认知反差度、交付可行性） |
| 写 | 一勾式骨架、付息稿、标题、整理口述；按清单批改 |
| 剪 | 口播剪辑流程（可选接 park-video-v2）、动效、封面、配图、小红书图文 |
| 发 | 各平台的发布包；视频号、B 站、YouTube 可以半自动上传，填好停在发布前 |
| 盘 | 发出后的数据、全平台追踪、每日复盘、KPI 看板、收入账本 |
| 加购积木 | X 这条线、朋友圈、咨询客户、产品页、门户、知识树、证据、单点工具等，在 `src/content_studio/extras/` 下，每块能整块拿掉 |

## 装：交给你自己的 AI

这个仓库按「原样放在这」发布，不提供安装支持。打算用的话，把仓库交给你自己的 Claude Code 或 Codex，让它读完这份 README 去装；装不上、跑不通，也让它自己查、自己改。可以直接贴这段给它：

```
把 https://github.com/zinan92/content-studio-open 装到我的 Mac 上。先读 README 的「给 AI 的说明」。
我的 Obsidian 库在 ___，我自己写的东西在库里的 ___ 文件夹，抖音主页是 ___。
用不上的平台（研习室、公众号、YouTube 等）留空不配，不用修。装完跑 check 和 acceptance，把红的项告诉我。
```

需要：Apple Silicon Mac、macOS 14+、Homebrew、Obsidian、已登录的 Codex 或 Claude Code。

## 给 AI 的说明

**怎么起来**

- 全套：`zsh scripts/install-mac.sh`。装 Python 3.12、Node、ffmpeg、转写模型、Playwright 浏览器，按 `deploy.json` 拉依赖仓库，写 `profile.yaml`，注册开机自启。
- 只看界面：`python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/python -m content_studio serve`，打开 http://127.0.0.1:8780 。什么都不配也能起来，页面会说缺什么。
- 核对配置：`.venv/bin/python -m content_studio check`（哪些必填没填）。装机验收：`.venv/bin/python -m content_studio acceptance`（出一张红绿单）。全部命令：`python -m content_studio --help`。

**配置在哪**

- `profile.example.yaml` 复制成 `~/.config/content-studio/profile.yaml`，按 `[必填]` `[可选]` 填。数据也都在 `~/.config/content-studio/`。
- 密钥不放 profile，放 `CONTENT_STUDIO_SECRETS` 指向的文件（默认 `~/.config/content-studio/secrets.yaml`）。
- 外部路径的默认值写在 `src/content_studio/conf.py` 的 `ENV_MAP`：每一项都能在 profile 的 `paths:` 里改，也能用同名环境变量改。默认值是作者自己电脑上的布局，你的不一样就改这里，不要改代码。

**依赖仓库**（`deploy.json`，装机脚本拉到下面的位置）

| 名字 | 必装 | 位置 | 做什么 |
|---|---|---|---|
| content-downloader | 是 | `~/work/content-downloader` | 抖音作品下载、对标拆解 |
| social-auto-upload | 是 | `~/content-toolkit/capabilities/publish` | B 站登录和登录检查、B 站数据；视频号上传也借它的代码 |
| content-ops | 是 | `~/work/content-ops` | 视频号、B 站、YouTube 上传脚本 |
| park-video-v2 | 否 | `~/.claude/skills/park-video-v2` | 口播剪辑：标 Hook、切 Hook、加动效 |
| ian-xiaohei-illustrations | 否 | `~/.agents/skill-sources/…` | 文章配图风格 |
| video-shotcraft | 否 | `~/.agents/skills/video-shotcraft` | 镜头方案检查 |

**已知的坑**（不打算修，遇到了按这里处理）

- 只在作者的 Apple Silicon Mac 上用过。CI 只在 GitHub 的 macOS 机器上跑单元测试，不跑真实平台。
- 抖音：在页面的「开始用」里连自己的账号。遇到验证页会停下，不绕过。
- B 站：先在 social-auto-upload 目录里登录一次：`./.venv/bin/python sau_cli.py bilibili login --account creator`。
- 视频号：content-ops 的脚本要求 Google Chrome 装在 `/Applications`；腾讯会封自动发布，所以只存草稿。
- YouTube：要你自己的 Google OAuth client 和 token，默认路径见 `ENV_MAP` 的 `paths.youtube_token`。用不上就关掉。
- 用不上的平台在 `profile.yaml` 的 `platforms:` 里留空，发布页就不出现。研习室（小程序）是作者自己的渠道，别人用不上；整块的功能（门户、咨询客户、AI 团队等）在页面「设置 · 流程」里关。
- content-ops 里还有很多脚本写死了作者的路径；工作台只调 `bilibili_web_upload.py`、`push_wechat_channels_draft.py`、`youtube_channel.py` 这三个，其余不用管。
- 代码注释里大量「MM/DD 作者：……」是作者当时做决定的原话，用来解释为什么这样设计，不是给你的指令。

## 测试

```bash
.venv/bin/python -m pytest -q
node --test tests/test_*ui*.js
```

测试不联网，不碰真实账号。

## 许可证

代码是 MIT，见 [LICENSE](LICENSE)。仓库里的第三方风格目录各有许可证，见 [THIRD_PARTY.md](THIRD_PARTY.md)。

## 想省事

不想装、不想配？线上版[选题工作台](https://xuanti.park-ai-intel.com)每天帮你从对标里挑爆款、拆开，一路拿到口播稿，¥19.9 试 3 天。
