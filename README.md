# True Pixel · 真像素重建

将像素风静态图按逻辑网格重建为原生分辨率的 RGBA PNG。离线运行，脚本依赖 Python、Pillow 与 NumPy。技能包位于 [skills/true-pixel](skills/true-pixel/SKILL.md)，可独立链接到 yts。

## 运行

在仓库根目录用 PowerShell 执行。最后一个路径是新的输出目录。

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r skills/true-pixel/requirements.txt
.venv/Scripts/python -B skills/true-pixel/scripts/true_pixel.py examples/lantern/input.png out/lantern --size 48x48 --alpha binary
```

省略 `--size` 自动估计两轴的网格周期和偏移。脚本统计可见颜色与透明度边缘的频谱，比较全图和分区的网格证据。水平或垂直线索薄弱、分区冲突或横纵格距相差明显时返回 2，并保留诊断供复核。指定尺寸时直接按画布分格。每格以中心加权票数选出主要近色组，从组内选取实际颜色；透明度单独按覆盖率计算。支持可选色板与二值透明。输出文件和退出状态见[技能说明](skills/true-pixel/SKILL.md)。

## 验证

```powershell
.venv/Scripts/python -B -m unittest discover -s tests -v
```

受控样本包含透明、半透明和单格细节。检查整数与非整数放大、裁切后网格偏移、轻模糊和中心点污染，以及混合网格、比例处理、色板、二值透明和已有目录保护。

[实图原件](examples/lantern/input.png)由内置 ImageGen 生成，画布 1254×1254。英文生成要求为单个带方形提手的黄铜提灯，琥珀色玻璃、一格高光、深蓝色描边，约 32×32 的粗像素，居中并保留透明留白。原始调用提示见[生成记录](examples/lantern/prompt.txt)。

- [自动检测报告](examples/lantern/auto/report.json)标出低置信度和横纵格距冲突，可对照[叠加网格](examples/lantern/auto/grid.png)。
- 以指定规格重建的 [32×32](examples/lantern/32/preview.png) 保留灯身和提手，玻璃高光被周围橙色覆盖。[48×48](examples/lantern/48/preview.png) 保留了一格亮白高光。两版都使用二值透明。
- 此例用于观察重建取舍。生成图没有可供逐格比较的原生底稿。
