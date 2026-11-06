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

不适合：不想装软件、只想打开网页就用的人。工作台不附送 AI 订阅，也不提供安装支持。

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

## 装

需要：Apple Silicon Mac、macOS 14+、Homebrew、Obsidian、已登录的 Codex 或 Claude Code。

一条命令装好（会装 Python、Node、ffmpeg、转写模型、浏览器组件，拉 `deploy.json` 里的依赖，注册开机自启）：

```bash
zsh scripts/install-mac.sh
```

只想先打开看看：

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m content_studio serve
```

打开 http://127.0.0.1:8780 。不配任何东西也能起来，页面会告诉你缺什么。

## 配置

复制 `profile.example.yaml` 成 `~/.config/content-studio/profile.yaml`，按里面的 `[必填]` `[可选]` 填。检查填得对不对：

```bash
.venv/bin/python -m content_studio check
```

数据都在 `~/.config/content-studio/`。密钥不放 profile，放 `CONTENT_STUDIO_SECRETS` 指向的文件（默认 `~/.config/content-studio/secrets.yaml`）。

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
