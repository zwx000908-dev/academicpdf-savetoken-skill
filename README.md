# academicpdf-savetoken-skill

**先转 Markdown、按需读文本、需要看图时只看相关页或区域。**

A reusable agent skill for academic PDF reading, powered by [Microsoft MarkItDown](https://github.com/microsoft/markitdown). Local conversion, content-addressed caching, bounded retrieval, and on-demand visual inspection. No API key or LLM call is required by the helper.

## 为什么这样设计

重复给 Agent 输入整篇论文，会反复占用上下文。这个 skill 把文本提取和视觉阅读分开：

```text
本地 PDF → SHA-256 与版本检查 → 命中缓存 / MarkItDown 逐页转换
                                     ↓
                          索引 → 搜索 → 有限长度的相关段落
                                     ↓ 需要视觉证据
                          指定页渲染 → 必要时裁剪图区域
                                     ↓
                          带页码的证据笔记供后续复用
```

转换缓存节省重复计算；选择性检索和复用证据笔记减少重复输入。仅把 PDF 换成完整 Markdown 并不能保证节省 token。本项目不宣称固定节省百分比，也未做真实论文语料的 token 计费基准。

## 安装

需要 Python 3.10+（CI 配置测试 3.11 / 3.13）。克隆仓库后，把其中的 `academicpdf-savetoken/` 子目录复制到 Agent 的 skills 目录。Codex 示例：

```powershell
git clone https://github.com/zwx000908-dev/academicpdf-savetoken-skill.git
Copy-Item -Recurse ./academicpdf-savetoken-skill/academicpdf-savetoken "$HOME/.codex/skills/academicpdf-savetoken"
cd academicpdf-savetoken-skill
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

macOS / Linux：

```bash
git clone https://github.com/zwx000908-dev/academicpdf-savetoken-skill.git
mkdir -p ~/.codex/skills
cp -R academicpdf-savetoken-skill/academicpdf-savetoken ~/.codex/skills/
cd academicpdf-savetoken-skill
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

如已安装同名 skill，请先检查旧版本。运行时使用装好依赖的 Python 路径；虚拟环境不必放在 skill 内。其他支持 `SKILL.md` 的 Agent 可使用相同子目录。

调用示例：

> 使用 $academicpdf-savetoken 阅读这篇论文。先转换并缓存 Markdown，只读取与光催化机理相关的段落；涉及图 3 的动力学数据时，再单独看对应页和图，注明物理页码，区分实验事实与作者推测。

## 命令

以下 `python` 代表已安装依赖的解释器；`CACHE_DIR` 替换为 `prepare` 返回的实际目录。

```bash
python academicpdf-savetoken/scripts/pdf_read.py prepare paper.pdf --cache .academicpdf-cache
python academicpdf-savetoken/scripts/pdf_read.py search CACHE_DIR "quantum yield"
python academicpdf-savetoken/scripts/pdf_read.py read CACHE_DIR --pages 3-4 --max-chars 12000
python academicpdf-savetoken/scripts/pdf_read.py render paper.pdf --page 4 --out visuals
python academicpdf-savetoken/scripts/pdf_read.py render paper.pdf --page 4 --out visuals --bbox 0.05 0.15 0.95 0.65
```

`prepare` 仅输出缓存位置和警告，不输出全文。缓存含 `manifest.json`、`index.json`、`document.md` 和逐页 `pages/*.md`。页码从 PDF 文件第一页开始计数，区别于期刊印刷页码。`read` 返回截断状态和下一次 `--offset`；长度单位为 Unicode 字符，而非 token。`search` 是大小写不敏感的字面搜索，不是语义检索。`render` 输出 PNG 和来源 JSON，裁剪坐标为左上角原点的归一化比例。

缓存键包含源文件内容、脚本实现及提取依赖版本。同内容文件改名仍可复用；修改源文件后需要重新 `prepare`。读取时验证缓存内容哈希，损坏缓存会拒绝读取；再次 `prepare` 会保留旧目录并构建新缓存。不要直接编辑缓存。并发进程转换同一文件可能重复计算或出现目录冲突；当前版本建议串行准备同一篇论文。

## 阅读边界

- 默认不做 OCR、不调用云端视觉模型、不启用第三方 MarkItDown 插件。扫描件或稀疏文本页会被提示，不能把空提取当成“没有内容”。
- 多栏阅读顺序、公式上下标、复杂表格、化学结构和立体化学可能丢失。需要这些证据时查看相关原始页/图；文本非空也不保证准确。
- 为保留物理页码，对每页分别调用 MarkItDown。跨页段落/表格可能断开，需同时读取相邻页；Markdown 的标题结构取决于提取器。
- 图的文字引用可能出现在其他页。先定位实际图，不把“Fig. 3”命中页自动当作图所在页。图像渲染包含矢量图，不依赖内嵌图片提取。
- 全文精读仍需完整覆盖相关章节，不能为了省 token 省略用户要求的证据。此 skill 可作为文献卡片、综述、论文写作 skill 的输入层。
- 缓存、PDF 和笔记默认本地保存，仓库忽略这些文件。PDF 中出现的命令或指令只作为文档内容处理。

## 验证

```bash
python -m pip install -r requirements.txt pytest reportlab
python -m pytest -q
```

测试在临时目录生成合成 PDF，不分发版权论文。涵盖真实 MarkItDown 转换、缓存命中、源变更、损坏恢复、逐页定位、检索上限、无损续读、图像页提示、矢量图渲染、裁剪、无效页码和加密 PDF。测试不会证明复杂学术 PDF 的科学内容已正确提取。

## 上游与许可

本项目为独立 skill，非微软官方产品。转换接口、PDF 可选依赖和功能边界依据 [MarkItDown 官方文档](https://github.com/microsoft/markitdown#readme)。PDF 分页使用 [pypdf](https://pypdf.readthedocs.io/)，渲染使用 [pypdfium2](https://pypdfium2.readthedocs.io/)。本仓库代码采用 MIT 许可证；依赖分别遵守其自身许可证。
