# 风格库整理与样图生成报告

更新：2026-10-10。仅修改数据和后端，未改前端、`tools.py`、`public.py`、`codes.py`，未 commit、push 或开 PR。原始六仓库只读且均保持干净；未联网查资料、未复制原仓图片视频。真实出图仅通过既有 `sandboxed_paint` 尝试两条，均被当前执行环境拒绝启动沙盒，没有生成样图。

## 上架统计

| 来源 | 收录风格 | 风格上架 | 风格不上架 | 语法上架 / 不上架 | 初次导入跳过 |
| --- | ---: | ---: | ---: | ---: | ---: |
| huashu-art-motion | 35 | 35 | 0 | 8 / 1 | 0 |
| opus-videos | 513 | 181 | 332 | 0 / 0 | 0 |
| ai-motion | 637 | 366 | 271 | 0 / 0 | 0 |
| mg-styles | 15 | 15 | 0 | 0 / 0 | 0 |
| handraw | 327 | 282 | 45 | 0 / 0 | 0 |
| gpt-image | 262 | 70 | 192 | 0 / 0 | 221 |
| 合计 | 1789 | 949 | 840 | 8 / 1 | 221 |

1789 个风格加 9 条语法，共 1798 条记录，每条都有布尔 `listed`；957 条上架，841 条不上架。上架风格按功能：生图 352、特效视频 181、动效 416。初次导入跳过的 221 条不在收录数据中，与本次保留但不上架的条目分开统计。

本次新增花叔英文 prompt 44 条（35 风格、9 语法），将 MG 15 条 prompt 的故事改为 `{script}`；共补齐或模板化 59 条 prompt。另补齐 Opus 的 55 条 summary、1 条 name。其他四来源的 prompt 与本轮前逐条完全相同，没有用描述或推文编提示词。

`listed=true` 只表示文字与输入槽可用，不代表已验证生成质量；全部 `status` 仍是 `draft`。上架条目 `needs=[]`，prompt 必须包含对应的 `{topic}` 或 `{script}`。`validate()` 对风格和语法同时执行这两条新约束。

## 不上架原因

下表为缺项次数，一条可能有多个缺项，不能相加当作条目数。逐来源计数同时记录在 `index.json` 的 `unlisted_reasons` 和 `grammar_unlisted_reasons`。

| 来源 | 为什么不上架 |
| --- | --- |
| 花叔 | 35 风格全上架；Y6 讲解员语法缺 `character-frames`、`voiceover`，虽补了 prompt，仍不上架。 |
| Opus | `prompt` 324、`reference` 51、`summary` 79、`name` 39。234 条原仓明确标为 partial 的提示词全部不上架；其余存在不可靠内容槽、固定故事或参考资料缺失。 |
| AI Motion | `file` 162、`prompt` 83、`source-inputs` 71、`scene-pair` 39、`keyframes` 20、`topic-specific-story` 3。依赖未提供的文件、前后场景、关键帧或参数，或缺可安全替换的脚本槽。 |
| MG 15 | 全部完成故事模板化，无待补项。 |
| 手绘 | `prompt` 45、`summary` 11。13 条特征词为空，32 条只写“参考绘本作者”；其中 11 条连视觉说明也缺，作品名不足以补写视觉细节。 |
| GPT Image | `prompt` 162、`reference_image` 61、`aspect` 22。原文缺损、额外变量未确定、依赖参考图，或比例不在当前合同枚举内；没有擅自补写或改映射。 |

## 数据口径与来源处理

- 风格与语法分别计数。`load_all()`、`by_function()` 仍返回全部收录风格；消费者通过 `listed` 筛选。`grammars()` 返回花叔语法，`get()` 可查两类，不展开排列组合。
- 仅用字符串替换 `{topic}` / `{script}`，不要对整段 prompt 用 `str.format()`，原文有代码及其他大括号。
- `path`、`preview` 均相对原仓库；仅远端预览填 null，没有下载媒体。保留来源授权、作者及手绘指定署名。
- `index.json` 的既有功能、类别、候选和跳过计数不变；新增风格与语法各自上架/不上架计数，以及按功能的上架/不上架计数。

### 花叔艺术动效

逐一读取 `references/风格配方/` 的 35 个编号配方与 `references/动画语法/` 的 9 张卡。依据配方写一段英文提示词，要求把 `{script}` 做成约 10 秒、自含 HTML/CSS/JS 的单文件网页动画；保留色板、材质、动作方式及禁忌，优先采用原文返修后结论。提示词是本次依授权从配方整理的模板，不冒充上游原生 prompt。

35 风格分类仍为时代标本 18、材料层 17。编号缺 07；INDEX、转场迁移测试、音轨说明不算独立风格。只有埃及、莫奈、像素有独立 showcase GIF 路径，未把总览图当作单条预览。

Y6 原文明说“素材和口播需自行提供，不能直接把本卡当作完整成片模板”，不附角色 sprite，也无独立参数化片段。其 prompt 保留用户提供角色帧及口播的前提，`needs=[character-frames, voiceover]`、`listed=false`；不以代码绘制的角色冒充原文要求的 AI 生帧。其余 8 语法上架。动画尚未生成验收。

### MG 15

逐条对照原仓 `prompts/*.md`。只在 Creative seed 中把具体人物、故事、品牌和文案换成 `{script}`，保留导演、输出、节奏、镜头动作、材质、配色、音效、制作步骤、规则与交付要求。15 条均保留原本的 10 秒 MP4 成片规范，不改成 HTML 输出规范。

花字技术路线中的 `pet-vlog footage layer` 改为 `{script} footage layer`；HUD 的固定上海坐标归故事内容，改为 `coordinates from {script}`。分别去掉 `topic-specific-route`、`coordinates` 缺项；10 条同时去掉 `prompt`、`topic-specific-story`。用脚本决定主体与坐标，不再绑定原演示故事。

### Opus 视频

以 `data/videos.json` 的 513 条为完整清单，`prompts/<slug>.md` 是对应镜像，不重复收录；保留四类与原作者。459 个不同提示词文本之外的 54 条同文作品按独立作者作品保留，不宣称它们是不同效果。

本轮依据原文补齐 55 条说明、1 条名称，包括原文只明确时长、用途的短提示词；说明注明原文未限定画风，不虚构视觉特征。`opus-0xevinho-436195` 只要求类似参考片的变体，补说明同时增加 `reference` 缺项，仍不上架。全部 prompt 保持本轮前原文不变。

### AI Motion

以原 `index.json.effects` 的 637 条手法为清单，保留 15 个 family 的中文分类；English Claude Code prompt 与 `effects/<slug>/README.md` 对应。已有目标/文字槽换为 `{script}`，其余文件、素材、前后场景、关键帧及参数需求保留，本轮只加 listed。11 份复合 recipe 不作为独立风格。

`morph-match-cut`、`giant-mask-reveal`、`card-flip-stack` 含固定示例故事，保留缺项不上架。来源 MIT 及概念引用作者归属保持原记录。

### 手绘

以当前画廊及 `references/styles.json` 的 327 个 FA–FH 编号为准；旧 MANIFEST/STYLES 的 001–327 编号不用于错配预览。8 类原分组、署名、色彩及排版维度保留，不进行组合扩充。

prompt 仍是画廊原格式“风格：编号，主题：{topic}”加该卡原始特征词；不是另写完整绘画指令。原特征词里服饰、角色、动物例子原样保留，实际主题适配仍需生成后验收。缺特征词或仅作者名的 45 条不上架。

### GPT Image

按英文 README 的 462 个 Case 拆为 483 个独立提示词单元：262 个保留、221 个初次导入跳过。保留可复用画法、材质、摄影及排版模板；固定品牌故事、纯修复或测试不收录。复杂变量、参考图、比例枚举缺项保持原样；本轮只加 listed。

保留 Case/变体的初次导入排除清单和原文片段，以便追溯；案例 91/104、137/141 等来源重复保留，不宣称视觉效果不同。name_en 保留原题，中文名以实际 prompt 为准。未联网核实外链或作者。

## 样图生成器

```bash
python3 scripts/style-samples.py --function image [--limit N] [--only id1,id2] [--topic "…"]
```

默认主题：`一个人用 AI 做自媒体，像同时指挥一支小乐队`。仅选 `listed=true` 的 image 风格，逐条串行替换 `{topic}`，追加“只用 image_gen 生成一张，不要运行命令、不要保存或移动文件；生成后只回复『好了』”，调用原有 `public.sandboxed_paint`。每条临时工作目录在调用前赋给 `public.CURRENT["dir"]`，结束、失败、中断均复位为 None 并清理目录。

取返回列表最后一张，保留比例与透明度，转 WebP（宽不超过 1200、质量 82）。临时文件编码成功后原子写入 `samples/<style-id>.webp`。已有 WebP 跳过；成功、失败、跳过均追加 `samples/log.jsonl`（id/status/seconds/error），失败继续下一条。`--limit` 计实际尝试（含失败，不含跳过）；Ctrl-C 记录中断并停止，CLI 返回 130。平均耗时不含跳过。

### 本轮真实调用

只执行一次 `python3 scripts/style-samples.py --function image --limit 2`：

| ID | 结果 | 耗时 | 原因 |
| --- | --- | ---: | --- |
| hd-fa-001 | 失败，未出图 | 0.011 秒 | sandbox-exec: sandbox_apply: Operation not permitted |
| hd-fa-002 | 失败，未出图 | 0.008 秒 | sandbox-exec: sandbox_apply: Operation not permitted |

这是沙盒启动失败，不是模型生图失败；没有进入 image_gen，也没有 WebP 可验收。真实日志保留在 `samples/log.jsonl`；没有重试或扩大批量。需在允许启动现有 macOS 沙盒的本机终端继续验证，脚本会重试这两条尚无 WebP 的记录。

## 本地来源版本

只以以下本地 checkout 为证据，没有检查远端是否更新。

| 来源 | 仓库 | HEAD | 授权 |
| --- | --- | --- | --- |
| 花叔艺术动效 | alchaincyf/huashu-art-motion | d861767d180008d27675819932070a670a3ae43f | MIT |
| Opus 视频 | yihui-dev/awesome-opus5-5-videos | 756290289742535eb0ac3817548f152e9759cc70 | MIT |
| AI Motion | gongnyang/awesome-ai-motion | 1e3c249073c61b42ceb556d7800f628d565d9312 | MIT；引用作品作者另行署名 |
| MG 15 | Vincentwei1021/mg-styles-15 | 49052d80bfaf9fa8412cc9710530e5e95a3b8d8c | MIT |
| 手绘 | yang0/handraw-style | 4eb29e2fcea3d9595d2f67b363e30ffdea338027 | MIT；保留指定署名 |
| GPT Image | EvoLinkAI/awesome-gpt-image-2-API-and-Prompts | e2a269ad1a055a0b4f6c1e170341c6c1aba30faa | CC0-1.0 |

## GPT Image 初次导入跳过明细

462 个案例按独立提示词拆成 483 个单元；262 个收录、221 个跳过。案例号对应原仓 `README.md` 的 `Case N`，变体编号对应同案例内的提示词顺序。源分类和原文开头片段也保留在 `index.json.skipped_items`，便于逐条复查。

| Case / 变体 | 原标题 | 类别 | 跳过原因 |
| --- | --- | --- | --- |
| 1 / 1 | E-commerce Main Image - Miniature Diorama Skincare Advertisement | 电商 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 2 / 1 | E-commerce Main Image - 9-Panel Product TVC Storyboard | 电商 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 3 / 1 | Burger hero image plus 9-cell ad storyboard | 电商 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 3 / 2 | Burger hero image plus 9-cell ad storyboard | 电商 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 4 / 1 | Döner Commercial Food Photography Set | 电商 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 6 / 1 | Ancient Palace Perfume Ad | 电商 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 8 / 1 | VOLT Goal Celebration Ad | 电商 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 8 / 2 | VOLT Goal Celebration Ad | 电商 | 配套15秒视频生成提示词，不属于本来源的图片风格。 |
| 9 / 1 | Lightning Storm Supercar Ad | 电商 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 11 / 1 | Miniature Brand Universe Shoe | 电商 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 12 / 1 | Romantic Smartphone Couple Scene Product Shot | 电商 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 13 / 1 | Floral Serum Product Shot | 电商 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 14 / 1 | Ingredient Callout Ice Cream Ad | 电商 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 15 / 1 | Spicy Chili Chutney Product Shot | 电商 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 17 / 1 | Luxury Chronograph Watch Ad | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 18 / 1 | Luxury chocolate campaign system | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 20 / 1 | Luxury Fragrance Campaign Portrait | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 21 / 1 | Berry Splash Cafe Campaign | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 21 / 2 | Berry Splash Cafe Campaign | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 22 / 1 | Fast Food Hero Poster | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 23 / 1 | Matcha Granola Ad Poster | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 23 / 2 | Matcha Granola Ad Poster | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 23 / 3 | Matcha Granola Ad Poster | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 25 / 1 | Foam Clogs Ad Poster | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 26 / 1 | Energy Drink Stadium Ad | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 28 / 1 | Adidas Futuristic Drop Ad Poster 9:16 | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 29 / 1 | Luxury Linen Texture Editorial Poster | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 30 / 1 | Luxury Watch Dramatic Beam Product Shot | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 31 / 1 | 可口可乐百事雪碧品牌 KV 对比 | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 32 / 1 | Luxury Sneaker Editorial Grid | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 33 / 1 | Wireless Earbuds Lifestyle Ad | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 34 / 1 | Kinder Joy Swing Chair Scene | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 35 / 1 | Invisible Shield Sunscreen Ad | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 37 / 1 | SPLASH Liquid Logo Fashion Poster | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 38 / 1 | OBSIDIAN Coffee Brand Campaign | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 39 / 1 | Coconut Paradise Skincare Ad | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 41 / 1 | Grape Reveal Can Product Shot | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 42 / 1 | Ray-Ban Giant Aviator Ad | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 43 / 1 | Noir Elixir Perfume Ad | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 46 / 1 | STARKIDZ Cosmic Telescope Ad | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 47 / 1 | Monumental Timepiece Fashion Ad | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 48 / 1 | Doodle Escape Studio Sprint | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 49 / 1 | Metro CCTV Thriller Frame | 广告创意 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 51 / 1 | Coastal Daydream Film Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 52 / 1 | Convenience Store Neon Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 55 / 1 | Wimbledon Broadcast Crowd Shot | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 56 / 1 | Rainy Street Golden Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 59 / 1 | Retro Newsstand Fashion Scene | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 69 / 1 | Busan Travel Journal Illustration | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 70 / 1 | Cinematic Volleyball Sports Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 73 / 1 | Cozy Bedroom Korean Girl Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 74 / 1 | Anime Brand Campaign Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 75 / 1 | Woman in Crystal Perfume Bottle | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 76 / 1 | Summer Campus Tesla Lifestyle Poster | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 77 / 1 | Bubble-Tea Shop Action Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 78 / 1 | Night Outdoor Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 82 / 1 | Reference-Based Portrait Consistency | 人像与摄影 | 重点是人物一致性、修图或身份约束，没有独立可复用的视觉风格。 |
| 83 / 1 | London Fashion Street Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 84 / 1 | Travel Selfie Portrait Reference | 人像与摄影 | 重点是人物一致性、修图或身份约束，没有独立可复用的视觉风格。 |
| 87 / 1 | Pixar 3D Character Design Sheet | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 88 / 1 | Matcha Goddess Beauty Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 90 / 1 | 写实感人物竖版照片 | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 92 / 1 | Editorial Male Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 95 / 1 | Korean Beauty Ultra-Realistic Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 100 / 1 | Cinematic Football Portrait Poster | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 101 / 1 | Switzerland Watercolor Travel Poster | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 102 / 1 | Cinematic Lifestyle Outdoor Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 103 / 1 | Luxury Cycling Storyboard Poster | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 105 / 1 | Cosmic Garden Fantasy Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 107 / 1 | Cat-Eye Glasses Fashion Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 109 / 1 | Clean Tech Advertisement Poster | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 111 / 1 | Korean Beauty Identity Portrait | 人像与摄影 | 重点是人物一致性、修图或身份约束，没有独立可复用的视觉风格。 |
| 112 / 1 | Hollywood Luxury Anime Fashion Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 113 / 1 | Identity Reference Beauty Portrait | 人像与摄影 | 重点是人物一致性、修图或身份约束，没有独立可复用的视觉风格。 |
| 115 / 1 | Negative Prompt Portrait Template | 人像与摄影 | 重点是人物一致性、修图或身份约束，没有独立可复用的视觉风格。 |
| 117 / 1 | Pixar 3D Character Design Sheet | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 120 / 1 | Brand Identity Portrait | 人像与摄影 | 重点是人物一致性、修图或身份约束，没有独立可复用的视觉风格。 |
| 121 / 1 | Outdoor Lifestyle Open Sky Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 123 / 1 | 沙滩场景丰腴人物写真 | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 124 / 1 | Photorealistic Editorial Seated Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 126 / 1 | Pakistan Miniature World Map Poster | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 127 / 1 | Japanese Film Aesthetic Airport Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 132 / 1 | Boho Stone-Wall Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 135 / 1 | Futuristic Martial Arts Heroine Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 136 / 1 | Under-Glass Worms-Eye Crowd Shot | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 142 / 1 | Nightlife Restaurant Flash Collage | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 146 / 1 | High Angle Cinematic Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 148 / 1 | Kawaii Character Side Profile Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 152 / 1 | Winter Wolf Cinematic Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 153 / 1 | Full Shot Man White Chair | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 154 / 1 | Eiffel Tower Low Angle Fashion Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 156 / 1 | Italian Summer Afternoon Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 157 / 1 | Rainy Night Cinematic Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 159 / 1 | Cozy Pastel Morning Overhead Lifestyle | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 160 / 1 | Stylish Woman Outside Cozy Café Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 161 / 1 | Luxury Streetwear Chrome Chair Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 162 / 1 | South Korea Graffiti Street Art Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 165 / 1 | Doll-ification Concept Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 167 / 1 | Face-Reference Consistent Portrait | 人像与摄影 | 重点是人物一致性、修图或身份约束，没有独立可复用的视觉风格。 |
| 168 / 1 | 日本コンビニ店員 昼夜対比写真 | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 170 / 1 | Face-Preserved Ultra-Realistic Portrait | 人像与摄影 | 重点是人物一致性、修图或身份约束，没有独立可复用的视觉风格。 |
| 172 / 1 | 파리 가로등 기댄 감성 전신 포즈 | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 173 / 1 | 深夜调酒师暗红酒吧封面写真 | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 175 / 1 | Airy Japanese Window Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 176 / 1 | 作者 Bench Iced Coffee Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 177 / 1 | Curtain Bang Close-Up Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 178 / 1 | Cyborg Prosthetic Close-Up | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 179 / 1 | Mediterranean Alley Sunlit Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 181 / 1 | Emerald Headwrap Editorial Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 182 / 1 | Late-Night Office Flash Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 183 / 1 | Late-Night Subway CCD Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 186 / 1 | Forced-Perspective Sneaker Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 187 / 1 | Cloud-Bloom Editorial Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 189 / 1 | Lantern Hiker Studio Portrait | 人像与摄影 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 193 / 1 | Tea Estate Storybook Collage | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 198 / 1 | Glowing Sailboat Night Illustration | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 199 / 1 | Istanbul Line-Art Travel Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 200 / 1 | Dark Western Outlaw Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 201 / 1 | Anime Streetwear Mascot Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 205 / 1 | Bangkok Swiss Typography Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 219 / 1 | 星河入梦 3D CG 插画 | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 226 / 1 | Pixar 3D Character Design Sheet | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 232 / 1 | Viral Food Infographic Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 235 / 1 | Football Player Dynamic Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 236 / 1 | Travel Food Advertisement Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 238 / 1 | Retro Cafe Scrapbook Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 239 / 1 | Blueberry Lavender Soda Scrapbook Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 241 / 1 | Editorial Fashion Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 245 / 1 | Roland Garros Tennis Trailer | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 247 / 1 | Eagle vs Lion Stadium Clash | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 248 / 1 | Original Anime Dev Board | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 251 / 1 | Surreal Inner Self Editorial Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 256 / 1 | 電子レンジ大明神キャラ設定ポスター | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 259 / 1 | Mixed-Media Train Platform Portrait | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 261 / 1 | Berries and Blossoms Infographic Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 264 / 1 | Cosmic Campfire Concept Art | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 267 / 1 | Glass Skeleton Study Desk | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 276 / 1 | Love Bites Cyberpunk Manga Cover | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 279 / 1 | Sleep-Deprived Chibi Creator | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 280 / 1 | Spring Garden Watercolor Couple | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 281 / 1 | Cosmic Anime Villain Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 285 / 1 | Cinematography Analysis Frame | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 290 / 1 | 3D Travel Ticket | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 291 / 1 | Luxury Birthday Poster 3:4 | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 292 / 1 | Window Girl Fashion Editorial | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 294 / 1 | Three-Frame Nightlife Collage | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 298 / 1 | Nighttime Japanese Theater Cinematic | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 304 / 1 | Japanese Ad Banner 2x2 Grid | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 305 / 1 | Argentina Football Uniform Promo | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 310 / 1 | Celestial Fantasy Oracle Storyboard | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 313 / 1 | Satellite Terrain Letter Typography Map | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 314 / 1 | Polish PRL Era Magazine Spread | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 315 / 1 | FIFA World Cup 2026 Throne Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 318 / 1 | World Cup National Team Fashion Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 319 / 1 | FIFA World Cup Country Emblem Badge | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 321 / 1 | Pixar 3D Kebab Maker Storyboard Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 322 / 1 | BMX Rider Streetwear Mixed-Media Collage | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 324 / 1 | Sony A7 Exploded Diagram | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 330 / 1 | Blockbuster Action Movie Shot | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 334 / 1 | Jellyfish City Above the Dunes | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 336 / 1 | AI Music Bootcamp Event Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 340 / 1 | Lion-Camel Ridge Demon Court | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 341 / 1 | Moscow Swiss Editorial Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 342 / 1 | Whispers in the Crowd Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 343 / 1 | Red Dress Editorial Portrait | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 344 / 1 | Golden Halo Fashion Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 345 / 1 | Ronaldo Tri-Zone Sports Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 347 / 1 | Whimsical Mirror Travel Journal | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 349 / 1 | Argentina Number 10 Sports Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 352 / 1 | Guangzhou Silk Ribbon Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 353 / 1 | Ronaldo Topographic Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 356 / 1 | Moody GQ Beach Cover | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 357 / 1 | Chrome Visor Side Profile | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 359 / 1 | CMYK Ronaldo Collector Poster | 海报与插画 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 360 / 1 | Cozy Lifestyle Sticker Grid | 角色设计 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 364 / 1 | Mecha Girl Sea-City Key Visual | 角色设计 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 365 / 1 | GTA 6 in Bangalore Flower Market | 角色设计 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 366 / 1 | Stylized 3D Skater Character | 角色设计 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 370 / 1 | 雨中灵姬东方幻想 3D CG 角色 | 角色设计 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 373 / 1 | Luminant Archivist Character Poster | 角色设计 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 376 / 1 | Pixar Banana Hero Character | 角色设计 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 378 / 1 | LEGO Football Collectible Figure | 角色设计 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 383 / 2 | 12-Panel Storyboard Poster | 界面与社交媒体样机 | 配套视频生成提示词，不属于本来源的图片风格。 |
| 393 / 1 | Sitcom Intro Storyboard Sheet | 界面与社交媒体样机 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 396 / 1 | Pet World Cup Storyboard Sheet | 界面与社交媒体样机 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 399 / 1 | Bazaar Heist Storyboard Card | 界面与社交媒体样机 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 400 / 1 | Luxury Starter Pack Vision Board | 界面与社交媒体样机 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 405 / 1 | Energy Drink Storyboard Grid | 界面与社交媒体样机 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 406 / 1 | Anime Short Film Dev Board | 界面与社交媒体样机 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 407 / 1 | Editorial Anatomy Infographic Poster | 界面与社交媒体样机 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 408 / 1 | Graphite Coffee-Shop Storyboard | 界面与社交媒体样机 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 409 / 1 | Venice Travel Vlogger Collage | 界面与社交媒体样机 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 419 / 1 | The King Still Breathes Masthead | 界面与社交媒体样机 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 419 / 2 | The King Still Breathes Masthead | 界面与社交媒体样机 | 配套视频生成提示词，不属于本来源的图片风格。 |
| 420 / 1 | Douyin Livestream Screenshot | 界面与社交媒体样机 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 421 / 1 | AR Grocery Overlay POV | 界面与社交媒体样机 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 426 / 1 | Livestream Commerce UI Mockup | 界面与社交媒体样机 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 429 / 1 | VOLT Rush Citrus Burst | 界面与社交媒体样机 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 432 / 1 | Sam Altman Bear Selfie | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 432 / 2 | Sam Altman Bear Selfie | 对比与社区示例 | 去背景编辑操作，没有独立视觉风格。 |
| 435 / 1 | Donut Heist Storyboard Sheet | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 436 / 1 | Sourdough Baker Storyboard | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 438 / 1 | Pancake Dad Storyboard | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 439 / 1 | Solar Desert Worldbuilding Kit | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 440 / 1 | Racer Character Model Sheet | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 442 / 1 | Chaotic Kitchen Freeze-Frame | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 447 / 1 | Continuous-Run Glitch Storyboard | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 449 / 1 | Dust Bunny Nature Documentary | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 449 / 2 | Dust Bunny Nature Documentary | 对比与社区示例 | 配套视频生成提示词，不属于本来源的图片风格。 |
| 450 / 1 | Action Storyboard Sheet | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 451 / 1 | Churro Maker Storyboard Poster | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 452 / 1 | Food Anime Storyboard Generator | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 453 / 1 | Weightless Morning Storyboard | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 454 / 1 | Pretzel Maker Storyboard | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 455 / 1 | Bird Nest Chair Concept Board | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 456 / 1 | Old Footage Restoration with GPT-Image 2 | 对比与社区示例 | 旧片修复或算数编辑测试，属于操作测试而非视觉风格。 |
| 458 / 1 | Coin Math Editing Test | 对比与社区示例 | 旧片修复或算数编辑测试，属于操作测试而非视觉风格。 |
| 460 / 1 | Pergola Blueprint Build Split | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 460 / 2 | Pergola Blueprint Build Split | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 460 / 3 | Pergola Blueprint Build Split | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |
| 461 / 1 | Dog Bone Spacecraft Morph | 对比与社区示例 | 包含固定人物、地点、产品或逐镜情节；主体内容与场景强绑定，不能只换主题保留原文。 |

## 验收边界与检查

- 所有数据保留 draft；上架状态只代表缺项和输入槽检查通过。真实出图被沙盒阻断，图像风格复现度、动画质量均未验收。
- 当前交付针对源码 checkout；未改包数据配置，也未验证 wheel 安装后的数据分发。
- 假出图测试验证筛选、主题替换、取最后图、尺寸/透明度、已有跳过、日志追加、失败继续、limit/only、空结果/损坏图片及 Ctrl-C 清理；不会调用真实服务。
- `python3 -m pytest -q tests/test_styles.py tests/test_style_samples.py tests/test_tools.py tests/test_tools_public.py`：57 passed，7.07 秒。
- `styles.validate()` 返回 `[]`；`git diff --check` 通过；新增脚本、测试、日志另做未跟踪文件空白检查，无错误。
- `gitleaks detect --source . --no-banner --redact`：850 个提交，未发现泄漏。后端独立只读复核未发现需修复问题。
- 六个原始仓库 `git status --porcelain` 均为空；本次未提交、推送或创建 PR。
