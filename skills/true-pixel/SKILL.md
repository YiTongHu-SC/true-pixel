---
name: true-pixel
description: 将 ImageGen 等工具生成的像素风图片重建为原生分辨率 PNG，支持识别像素网格、指定精灵尺寸、透明边缘与色板，并输出网格对照图。
---

# 真像素重建

从当前技能目录运行 `scripts/true_pixel.py`。Python 3.10+ 需要 Pillow 和 NumPy（见 `requirements.txt`）。yts 本地作者项目在仓库根目录建有虚拟环境时，优先使用该环境的 Python；作者目录可由 `yts status true-pixel` 查得。独立使用可在虚拟环境中执行 `python -m pip install -r requirements.txt`。

```text
python scripts/true_pixel.py INPUT.png NEW_OUTPUT_DIR
python scripts/true_pixel.py INPUT.png NEW_OUTPUT_DIR --size 32x32 --alpha binary
```

有明确素材尺寸时用 `--size 宽x高`，保留整张画布和留白。比例冲突时按素材用途选择居中裁切 `--fit crop` 或透明补边 `--fit pad`。硬边图标可用 `--alpha binary`，默认保留透明度。可用 `--palette 色卡.png` 映射至色卡可见颜色，最多 256 色，无抖动。

未知尺寸时先自动识别。退出码 0 表示已输出 `native.png`；2 表示需要复核，读取 `report.json` 的 issues、两轴格距、偏移和候选，查看 `grid.png`。两轴都有候选时还会生成 `candidate.png` 和整数倍 `preview.png`。无法定位网格时用用户给出的规格；若需估算，展示预览并标明重建尺寸的依据。退出码 1 表示参数或文件错误。

交付原生 PNG，另附预览帮助核对轮廓、孔洞与高光。重复尝试使用新的输出目录，保留原图。自动模式针对单张静态图中近似水平、垂直的统一网格；整图只有少数色块或背景和主体像素尺度不同时，宜指定尺寸。
