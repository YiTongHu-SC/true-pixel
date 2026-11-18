"""Recover an axis-aligned logical pixel grid and write inspectable PNGs."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageOps


def candidates(profile):
    """Concentration of edge mass at each comb frequency, with free phase."""
    length = len(profile)
    mass = float(profile.sum())
    if length < 8 or mass < 1e-5:
        return []
    fft_size = 1 << (16 * length - 1).bit_length()
    spectrum = np.abs(np.fft.rfft(profile, fft_size)) / mass
    low = max(1, math.ceil(fft_size * 3 / length))
    high = fft_size // 2
    peaks = [i for i in range(low, high + 1)
             if spectrum[i] >= spectrum[i - 1]
             and (i == high or spectrum[i] > spectrum[i + 1])]
    positions = np.arange(length)
    options = []
    for i in sorted(peaks, key=lambda k: -spectrum[k])[:24]:
        frequency = i / fft_size
        if i < high:
            left, center, right = spectrum[i - 1:i + 2]
            curvature = left + right - 2 * center
            if curvature < 0:
                frequency += float((left - right) / (2 * curvature)) / fft_size
        pitch = 1 / frequency
        # An integer grid accumulates no rounding drift across the canvas.
        if abs(pitch - round(pitch)) * length / pitch < 0.25:
            pitch = float(round(pitch))
        phase_vector = profile @ np.exp(2j * np.pi * positions / pitch)
        offset = float(np.angle(phase_vector) * pitch / (2 * np.pi)) % pitch
        if min(offset, pitch - offset) < 0.45:
            offset = 0.0
        bins = np.rint((positions - offset) / pitch).astype(int)
        energy = np.bincount(bins - bins.min(), weights=profile)
        support = int(np.count_nonzero(energy > energy.max() * 0.05))
        options.append(dict(pitch=float(pitch), offset=offset,
                            score=round(float(abs(phase_vector) / mass), 4),
                            supported_lines=support))
    if not options:
        return []
    best = max(o["score"] for o in options)
    # Perfect blocks also align with every integer divisor of their pitch.
    # Choose the coarsest nearly equally supported period.
    near = [o for o in options if o["score"] >= best * 0.94 and o["supported_lines"] >= 3]
    chosen = max(near or options[:1], key=lambda o: o["pitch"])
    return [chosen] + [o for o in options if o is not chosen][:4]


def detect_axis(edges):
    profile = edges.sum(axis=0, dtype=np.float64)
    options = candidates(profile)
    if not options:
        return [], ["no_periodic_edges"]
    chosen = options[0]
    reasons = []
    if chosen["score"] < 0.56 or chosen["supported_lines"] < 4:
        reasons.append("weak_grid")
    for region in np.array_split(edges, 3):
        local_profile = region.sum(axis=0, dtype=np.float64)
        if local_profile.sum() < 0.12 * profile.sum():
            continue
        local = candidates(local_profile)
        if local and local[0]["score"] >= 0.60 and local[0]["supported_lines"] >= 4:
            relative = abs(local[0]["pitch"] / chosen["pitch"] - 1)
            phase = abs(local[0]["offset"] - chosen["offset"]) / chosen["pitch"]
            if relative > 0.07 or abs(phase - round(phase)) > 0.22:
                reasons.append("regional_grid_disagreement")
                break
    return options, reasons


def detect(im):
    rgba = np.asarray(im, dtype=np.float32)
    rgba[:, :, :3] *= rgba[:, :, 3:4] / 255
    axes = []
    issues = []
    for name, data in (("x", rgba), ("y", rgba.transpose(1, 0, 2))):
        edges = np.zeros(data.shape[:2], dtype=np.float32)
        edges[:, 1:] = np.max(np.abs(data[:, 1:] - data[:, :-1]), axis=2)
        options, reasons = detect_axis(edges)
        axes.append(options)
        issues.extend(name + "_" + reason for reason in reasons)
    if all(axes) and abs(math.log(axes[0][0]["pitch"] / axes[1][0]["pitch"])) > 0.15:
        issues.append("inconsistent_axis_scales")
    return axes, issues


def boundaries(length, model):
    # Keep partial cells at either canvas edge. Suppress sub-half-pixel slivers.
    interior = np.arange(model["offset"], length, model["pitch"])
    return np.unique(np.rint(np.r_[0, interior, length]).astype(int))


def native_size(value):
    match = re.fullmatch(r"([1-9]\d*)[xX]([1-9]\d*)", value)
    if not match:
        raise argparse.ArgumentTypeError("use WIDTHxHEIGHT, for example 32x32")
    return tuple(map(int, match.groups()))


def fit_canvas(im, size, fit):
    w, h = im.size
    tw, th = size
    if w * th == h * tw:
        return im
    if fit is None:
        raise ValueError("aspect ratios differ; choose --fit crop or --fit pad")
    scale = (min if fit == "crop" else max)(w / tw, h / th)
    fw, fh = max(1, round(tw * scale)), max(1, round(th * scale))
    if fw * fh > max(w * h * 4, 16_777_216):
        raise ValueError("padded canvas too large; choose crop or a closer aspect ratio")
    left, top = (w - fw) // 2, (h - fh) // 2
    # An out-of-canvas crop on RGBA fills missing pixels with transparent black.
    return im.crop((left, top, left + fw, top + fh))


def sample_cell(cell):
    h, w = cell.shape[:2]
    if np.all(cell == cell[0, 0]):
        return cell[0, 0]
    # Separable center weights: boundary antialiasing gets a smaller vote.
    def weights(n):
        return 1.0 - np.abs((np.arange(n) + 0.5) * 2 / n - 1)
    weight = np.outer(weights(h), weights(w)).ravel()
    values = cell.reshape(-1, 4)
    alpha = values[:, 3]
    coverage = round(float(np.average(alpha, weights=weight)))
    # With fractional pitch, rounding a boundary may include one thin strip
    # of the adjacent cell. Preserve an effectively uniform alpha plateau.
    alpha_votes = np.bincount(alpha, weights=weight, minlength=256)
    dominant_alpha = int(alpha_votes.argmax())
    if alpha_votes[dominant_alpha] >= 0.96 * weight.sum():
        coverage = dominant_alpha
    if coverage == 0:
        return (0, 0, 0, 0)
    visible = alpha > 0
    rgb = values[visible, :3]
    votes = weight[visible] * alpha[visible]
    bins = rgb.astype(np.int32) // 16
    keys = bins @ np.array([256, 16, 1])
    labels, inv = np.unique(keys, return_inverse=True)
    winner = labels[np.bincount(inv, weights=votes).argmax()]
    group = keys == winner
    colors = rgb[group].astype(float)
    center = np.average(colors, axis=0, weights=votes[group])
    selected = colors[np.square(colors - center).sum(axis=1).argmin()]
    return (*selected, coverage)


def detail_point(value):
    if not re.fullmatch(r"[0-9]+,[0-9]+", value):
        raise argparse.ArgumentTypeError("use zero-based target X,Y, for example 12,8")
    return tuple(map(int, value.split(",")))


def refine_point(data, xs, ys, x, y, result):
    """Test nearby sampling positions for one artist-selected feature pixel."""
    x0, x1 = map(int, xs[x:x + 2])
    y0, y1 = map(int, ys[y:y + 2])
    w, h = x1 - x0, y1 - y0
    baseline = result[y, x, :3].astype(float)
    record = dict(point=[x, y], before=baseline.astype(int).tolist())
    if result[y, x, 3] == 0:
        return dict(record, selected="transparent", trials=[])

    cell = data[y0:y1, x0:x1]
    visible = cell[cell[:, :, 3] > 0]
    # Do not promote the RGB of a nearly invisible fringe to a solid mark.
    alpha = visible[:, 3]
    colors = visible[alpha >= 0.5 * alpha.max(), :3].astype(float)

    def closest_source_color(color):
        return colors[np.square(colors - color).sum(axis=1).argmin()]

    # The ordinary vote can miss a thin mark. The unshifted coverage gives
    # its direction and strength. At an explicit detail point, give the
    # missing contrast twice its area-average weight when ranking candidates.
    mean = np.average(visible[:, :3], axis=0, weights=alpha.astype(float))
    target = baseline + 2 * (mean - baseline)
    options = [("baseline", baseline)]
    trials = []
    step_x, step_y = (w + 2) // 4, (h + 2) // 4
    height, width = data.shape[:2]
    seen = set()
    for dy in (0, -step_y, step_y):
        for dx in (0, -step_x, step_x):
            left = min(max(x0 + dx, 0), width - w)
            top = min(max(y0 + dy, 0), height - h)
            if (left, top) in seen:
                continue
            seen.add((left, top))
            sampled = sample_cell(data[top:top + h, left:left + w])
            offset = [left - x0, top - y0]
            if sampled[3] == 0:
                trials.append(dict(offset=offset, rgb=None))
                continue
            # Restrict candidates to colors present in this target cell.
            color = closest_source_color(sampled[:3])
            trials.append(dict(offset=offset, rgb=color.astype(int).tolist()))
            options.append((offset, color))
    options.append(("coverage", closest_source_color(mean)))
    selected, color = min(options, key=lambda item: np.square(item[1] - target).sum())
    result[y, x, :3] = color
    return dict(record, selected=selected, before_palette=color.astype(int).tolist(),
                trials=trials)


def reconstruct(im, xs, ys, alpha_mode, palette, points=(), detail_report=None):
    data = np.asarray(im)
    if len(xs) == im.width + 1 and len(ys) == im.height + 1:
        result = data.copy()
    else:
        result = np.empty((len(ys) - 1, len(xs) - 1, 4), dtype=np.uint8)
        for row, (y0, y1) in enumerate(zip(ys, ys[1:])):
            for col, (x0, x1) in enumerate(zip(xs, xs[1:])):
                result[row, col] = sample_cell(data[y0:y1, x0:x1])
    if alpha_mode == "binary":
        result[:, :, 3] = (result[:, :, 3] >= 128) * 255
    visible = result[:, :, 3] > 0
    result[~visible] = 0
    for x, y in points:
        detail = refine_point(data, xs, ys, x, y, result)
        if detail_report is not None:
            detail_report.append(detail)
    if palette is not None and visible.any():
        rgb, inv = np.unique(result[visible, :3], axis=0, return_inverse=True)
        mapped = np.empty_like(rgb)
        for start in range(0, len(rgb), 512):
            batch = rgb[start:start + 512].astype(np.int32)
            dist = np.square(batch[:, None, :] - palette).sum(axis=2)
            mapped[start:start + len(batch)] = palette[dist.argmin(axis=1)]
        result[visible, :3] = mapped[inv]
    return Image.fromarray(result)


def read_palette(path):
    with Image.open(path) as image:
        data = np.asarray(image.convert("RGBA")).reshape(-1, 4)
    colors = np.unique(data[data[:, 3] > 0, :3], axis=0)
    if not 1 <= len(colors) <= 256:
        raise ValueError("palette PNG must contain 1–256 visible RGB colors")
    return colors.astype(np.int32)


def run(args):
    if args.output.exists():
        raise ValueError("output directory already exists; choose a new path")
    with Image.open(args.input) as image:
        if getattr(image, "n_frames", 1) != 1:
            raise ValueError("supply one static image")
        im = ImageOps.exif_transpose(image).convert("RGBA")
    original_size = im.size
    if args.fit and not args.size:
        raise ValueError("--fit requires --size")
    if args.detail_point and not args.size:
        raise ValueError("--detail-point requires --size")
    points = list(dict.fromkeys(args.detail_point))
    if any(x >= args.size[0] or y >= args.size[1] for x, y in points):
        raise ValueError("detail point outside target canvas")
    report = dict(input_size=original_size, alpha=args.alpha, fit=args.fit,
                  palette=args.palette.name if args.palette else None)
    issues = []
    if args.size:
        im = fit_canvas(im, args.size, args.fit)
        if any(t > s for t, s in zip(args.size, im.size)):
            raise ValueError("target exceeds available source pixels")
        axes = [[dict(pitch=n / t, offset=0)] for n, t in zip(im.size, args.size)]
        bounds = [np.rint(np.linspace(0, n, t + 1)).astype(int)
                  for n, t in zip(im.size, args.size)]
    else:
        axes, issues = detect(im)
        bounds = [boundaries(n, options[0]) if options else np.array([0, n])
                  for n, options in zip(im.size, axes)]
    xs, ys = bounds
    inferred = all(axes)
    report.update(mode="specified" if args.size else "auto",
                  canvas_size=im.size, native_size=[len(xs)-1, len(ys)-1] if inferred else None,
                  x_candidates=axes[0], y_candidates=axes[1],
                  status="review" if issues else "ok", issues=issues)
    palette = read_palette(args.palette) if args.palette else None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as tmp:
        dest = Path(tmp) / "result"
        dest.mkdir()
        overlay = im.copy()
        guides = Image.new("RGBA", im.size)
        draw = ImageDraw.Draw(guides)
        for x in xs[1:-1]:
            draw.line((int(x), 0, int(x), im.height), fill=(255, 50, 150, 120))
        for y in ys[1:-1]:
            draw.line((0, int(y), im.width, int(y)), fill=(24, 220, 255, 120))
        overlay.alpha_composite(guides)
        overlay.save(dest / "grid.png")
        if inferred:
            details = []
            native = reconstruct(im, xs, ys, args.alpha, palette, points, details)
            if details:
                for item in details:
                    item["output"] = list(native.getpixel(tuple(item["point"])))
                report["detail_points"] = details
            native.save(dest / ("candidate.png" if issues else "native.png"))
            scale = min(8, max(1, 2048 // max(native.size)))
            native.resize((native.width * scale, native.height * scale),
                          Image.Resampling.NEAREST).save(dest / "preview.png")
            report["preview_scale"] = scale
        (dest / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        os.rename(dest, args.output)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", type=Path)
    p.add_argument("output", type=Path, help="new result directory")
    p.add_argument("--size", type=native_size)
    p.add_argument("--detail-point", type=detail_point, action="append", default=[],
                   metavar="X,Y", help="refine RGB at one target pixel; repeat for more points")
    p.add_argument("--fit", choices=["crop", "pad"])
    p.add_argument("--alpha", choices=["preserve", "binary"], default="preserve")
    p.add_argument("--palette", type=Path, help="PNG swatch with up to 256 visible colors")
    a = p.parse_args()
    try:
        report = run(a)
    except (ValueError, OSError) as exc:
        p.exit(1, f"{exc}\n")
    print(json.dumps(report, ensure_ascii=True))
    return 2 if report["status"] == "review" else 0


if __name__ == "__main__":
    raise SystemExit(main())
