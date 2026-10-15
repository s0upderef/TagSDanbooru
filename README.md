# TagSDanbooru · Danbooru 标签助手

![GitHub stars](https://img.shields.io/github/stars/s0upderef/TagSDanbooru?style=flat-square&label=stars)
![GitHub last commit](https://img.shields.io/github/last-commit/s0upderef/TagSDanbooru?style=flat-square)

本地运行的 Danbooru 标签助手：搜标签、挑组合、出提示词，顺手接本机 ComfyUI 看一眼效果。标签数据和前端依赖全部随仓库附带，**不联网也能用**。

## ✨ 亮点

- **15 万条标签全库**：模糊搜索、自动补全、分类筛选。
- **中文 + 两级分类**：热度越高的词条越完整；每个词条只有一个一级、一个二级，同类词按「长在哪 / 穿在哪」收进同一个桶，不会散在两处。
- **提示词一条龙**：点选组合、拖动排序、实时预览、多格式复制；粘贴一整段现成提示词能自动拆成标签；也能导出 wildcard。
- **出图工作台（可选）**：正向提示词就是上面选好的标签，参数读你自己的工作流；出好的图按批次、按天收进画廊，灯箱能缩放看细节，删除两步确认并进回收站可还原。
- **零 CDN**：断网、代理抖动都是完整界面。

## 🚀 快速开始

1. 双击根目录 **`启动.bat`**（会自动找可用的 python，并顺手拉起 ComfyUI）。
2. 自动打开本地页面，开始挑标签。
3. 收工点工作台里的「⏻ 关闭服务」，或直接关掉命令行窗口。

> 只用标签助手、不出图的话，ComfyUI 可以完全忽略。

## 🗂 数据

- 词库随仓库附带：15 万条 danbooru 标签，含中文译名与两级分类；中文和分类都按热度逐批补齐，越热门的词条越完整。
- 每个词条只有一个一级、一个二级分类，没有第三层；同类词按「长在哪 / 穿在哪」收进同一个桶，不会散在两处。
- 画师 / 角色 / 作品名只用名字检索，不铺分类。

## 📸 数据源

[Danbooru](https://danbooru.donmai.us/) · [SD WebUI Tag Autocomplete](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete) · [dbr-e621-lists-archive](https://github.com/DraconicDragon/dbr-e621-lists-archive)

---

给用 Stable Diffusion / ComfyUI、习惯用大量精细标签写提示词的人。告别繁琐的标签整理，专注创作本身。

提交信息：英文、措辞中性。
