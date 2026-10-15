# TagSDanbooru · Danbooru 标签助手

![GitHub stars](https://img.shields.io/github/stars/s0upderef/TagSDanbooru?style=flat-square&label=stars)
![GitHub last commit](https://img.shields.io/github/last-commit/s0upderef/TagSDanbooru?style=flat-square)
![No CDN](https://img.shields.io/badge/%E4%B8%8D%E4%BE%9D%E8%B5%96%20CDN-%E7%A6%BB%E7%BA%BF%E5%8F%AF%E7%94%A8-brightgreen?style=flat-square)

本地运行的 Danbooru 标签助手：搜标签、挑组合、出提示词，顺手接本机 ComfyUI 看一眼效果。标签数据和前端依赖全部随仓库附带，**不联网也能用**。

## ✨ 亮点

- **15 万条标签全库**：模糊搜索、自动补全、分类筛选。
- **人气前 20,000 条中文已补齐**；热门词条按 **人物 → 构图取景 → 背景** 两级分类，页面按钮就按这个优先级排（二级桶有服装 / 五官 / 表情 / 发型 / 体貌特征 / 物种 / 姿势动作 / 配饰…）。
- **提示词一条龙**：点选组合、自由拖排序、实时预览、多格式复制；**粘贴一整段现成提示词会自动拆成标签**（认 `(tag:1.15)` 权重）。
- **导出 wildcard**：SimpAI / Fooocus / A1111-Forge / ComfyUI 都能直接用。
- **出图工作台**：接本机 ComfyUI 随手出图，参数直接读你自己的工作流。
- **零 CDN**：Tailwind、图标字体、CSV 解析、拖拽排序都在 `_internal/vendor/`，断网、代理抖动都是完整界面。

## 🚀 快速开始

1. 双击根目录 **`启动.bat`**（脚本会自动找可用的 python，ComfyUI 自带的那个最省事）。
2. 自动打开独立页面窗口 `http://127.0.0.1:9000/TagSDanbooru.html`，同时拉起 ComfyUI。
3. 收工点工作台里的「⏻ 关闭服务」，或直接关掉那个命令行窗口。

> 只用标签助手、不用出图的话，ComfyUI 可以完全忽略。
> 反复双击 `启动.bat` 不会堆窗口：新的一次会让上一次干净退出。

## 🎨 出图工作台（可选）

- **正向提示词就是上面的「已选标签」**，一份数据两处用；要改就改标签板（或直接粘贴解析）。
- **出图时不动已有画廊**：新批次画在独立的「本次出图」区，已经出好的图原地保留。
- 参数（模型 / 采样器 / 步数 / CFG / 尺寸 / 张数 / 系列）默认从工作流 `_internal/workflows/workflow.json` 读取；**换成你自己的工作流也行**：把 ComfyUI 导出的 API 格式 JSON 放进 `_internal/workflows/`，再改 `_internal/config.json` 的 `paths.workflow` 即可。自带的 `workflow.json` 里 Checkpoint 是**占位名** `your-checkpoint.safetensors`，打开页面在下拉框选你自己的模型就行（页面只把这次的选择发给 ComfyUI，不改你的文件）。**画风由工作流的「正向base」（节点 9）决定**，页面「工作流预设词」里可以直接改并保存。
- 出图按**系列**归档：`_internal/output/<系列>/<批次>/01_seedXXX.png` 加一份 `prompt.json`。

## 🖼 结果画廊

- 点缩略图看灯箱：**下方按原顺序列出这张图的提示词，中文在前、英文在后**，`←` `→` 切换。
- 删除四种粒度，全部**两步确认 + 送回收站可还原**：单张（缩略图垃圾桶）/ 某一批 / 某个系列（卡片右侧垃圾桶）/ 全部出图。
- 在资源管理器里动过 `output/` 之后，点「刷新图片」或切回窗口会自动同步。

## 🗂 数据

- 来源：danbooru **2025-05-01** 快照，15 万行，随仓库附带 `_internal/data/tagsd_danbooru_zh.csv`。
- **中文**：热度前 20,000 名 100% 补齐，长尾按批推进。
- **分类**：12 个一级（人物 / 构图取景 / 背景 / 画面 / 物件 / 元标签 / 反向 / 内置分类-禁，加查询用的 kontext指令 / 角色 / 画师 / 作品），二级做过合并（最多 16 个）；画师 / 角色 / 作品名不铺分类。
- 前 20k 实用词条已分类 **86%**，其余按热度逐批补，待办清单在 `_internal/dev/reports/unmatched_20000.txt`。
- 工具：`classify_tags.py`（分类 + 二级合并）、`audit_tags.py`（覆盖率体检）、`check_prompt.py`（写词前体检）、`gen.py`（命令行出图）、`contact_sheet.py`（出图后拼检视图）。

## 📸 数据源

[Danbooru](https://danbooru.donmai.us/) · [SD WebUI Tag Autocomplete](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete) · [dbr-e621-lists-archive](https://github.com/DraconicDragon/dbr-e621-lists-archive)

---

给用 Stable Diffusion / ComfyUI、习惯用大量精细标签写提示词的人。告别繁琐的标签整理，专注创作本身。