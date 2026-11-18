# True Pixel · 真像素重建

True Pixel 把放大过的像素画或 AI 生成的像素风图片，重建成可以直接用在游戏里的小尺寸透明 PNG。你可以指定角色的宽高、保留半透明边缘，或让所有可见像素只使用项目色板中的颜色。转换在本机完成，需要 Python 3.10+、Pillow 和 NumPy。

## 示例 · 银发药剂师

这位银发药剂师来自 `godot-lab` 实验 001。左边是 **1024×1024 待机原图**，右边是 **96×96 像素重建图**。两边保留相同的取景和角色大小，方便对照帽沿、背篓和鞋尖的轮廓。

![药剂师全身对比，左为原图，右为二值透明的 96×96 重建结果，两侧角色等大](examples/herbalist/comparison.png)

**脸部细节**取自两图的同一位置。右侧区域在成品中只有 **24×18 像素**，用最近邻放大后，可以逐格对照刘海、眼睛高光和鼻尖的变化。

![脸部细节对比，左为原图局部，右为相同区域的像素重建局部](examples/herbalist/detail-comparison.png)

[查看透明原图](examples/herbalist/input.png) · [下载 96×96 透明 PNG](examples/herbalist/native.png)

## 安装为 AI 技能

把下面这句话发给支持安装 Agent Skills 的 AI 助手即可。

> 请从 https://github.com/YiTongHu-SC/true-pixel/tree/main/skills/true-pixel 安装并启用 true-pixel 技能，在运行该技能的 Python 环境中安装 requirements.txt 里的依赖。

**手动安装**也可以。克隆仓库，将整个 `skills/true-pixel` 目录复制到助手的技能目录。例如 Codex 的用户级路径是 `~/.agents/skills/true-pixel/`，复制后应能直接看到其中的 `SKILL.md`。在技能目录运行 `python -m pip install -r requirements.txt`，然后新开一个会话。

安装后可以直接说：“用 true-pixel 把这张角色图重建为 96×96，背景透明，颜色限制在我附上的色板里。给我原生 PNG 和放大预览。”

## 在命令行复现示例

在已激活的 Python 3.10+ 虚拟环境中运行：

```sh
git clone https://github.com/YiTongHu-SC/true-pixel.git
cd true-pixel
python -m pip install -r skills/true-pixel/requirements.txt
python skills/true-pixel/scripts/true_pixel.py examples/herbalist/input.png out/herbalist --size 96x96 --alpha binary
```

打开 `out/herbalist/native.png` 取用成品，打开 `out/herbalist/preview.png` 检查细节。每次运行使用新的输出目录。

## 选择尺寸、边缘和色板

| 需求 | 参数 | 处理方式 |
| --- | --- | --- |
| 从放大图恢复原尺寸 | 省略 `--size` | 分别估计横纵网格的间距和起点。适合全图使用统一、水平和垂直像素网格的静态图。 |
| 按游戏规格制作精灵 | `--size 32x48` | 按指定宽高分格取色。支持非方形画布和非整数缩放比例，目标宽高须在处理后画布的像素尺寸以内。 |
| 原图和目标比例不同 | `--fit pad` 或 `--fit crop` | 搭配 `--size` 使用。前者居中补透明边并保留全图，后者居中裁切以填满目标。 |
| 保留半透明或制作硬边 | `--alpha preserve` 或 `--alpha binary` | 默认保留透明度。选 `binary` 时，Alpha 小于 128 的像素全透明，其余全不透明。 |
| 统一到固定色值 | `--palette palette.png` | 色板 PNG 可由 1–256 种不同的可见 RGB 颜色组成。每个可见输出像素映射到 RGB 距离最近的色板值，无抖动。透明度单独处理。 |

## 判断结果

| 退出码 | 含义 | 接下来怎么做 |
| --- | --- | --- |
| `0` | 已生成 `native.png` | 使用原生 PNG，用 `preview.png` 查看整数倍放大效果。 |
| `2` | 自动网格需要复核 | 查看 `grid.png` 和 `report.json` 中的 `issues`。两轴都有候选时，可查看 `candidate.png` 和预览。知道目标尺寸时，用 `--size` 重新运行。 |
| `1` | 输入或输出处理失败 | 按终端错误检查图片、色板、宽高比和输出目录。 |

AI 助手可读取[技能入口](skills/true-pixel/SKILL.md)获取调用约定。另有[提灯示例](examples/lantern)，可对照同一张图在 32×32 和 48×48 下的高光差异。仓库根目录运行 `python -m unittest discover -s tests -v` 可执行回归测试。
