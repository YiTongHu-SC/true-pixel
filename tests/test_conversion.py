import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageFilter


CLI = Path(__file__).resolve().parents[1] / "skills/true-pixel/scripts/true_pixel.py"
NEAREST = Image.Resampling.NEAREST


def reference():
    colors = np.array([[0, 0, 0, 0], [12, 36, 54, 255], [229, 100, 10, 255],
                       [255, 240, 230, 255], [10, 180, 110, 115]], dtype="uint8")
    rng = np.random.default_rng(441)
    return Image.fromarray(colors[rng.integers(0, len(colors), (18, 24))])


class Conversion(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / "source.png"
        self.dest = self.root / "result"

    def convert(self, image, *args, code=0):
        image.save(self.source)
        result = subprocess.run([sys.executable, "-B", str(CLI), str(self.source),
                                 str(self.dest), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(code, result.returncode, result.stdout + result.stderr)
        if code != 1:
            return json.loads((self.dest / "report.json").read_text())

    def output(self):
        with Image.open(self.dest / "native.png") as image:
            return np.array(image)

    def test_auto_exact(self):
        orig = reference()
        report = self.convert(orig.resize((192, 144), NEAREST))
        self.assertEqual(report["native_size"], [24, 18])
        np.testing.assert_array_equal(self.output(), np.asarray(orig))

    def test_fractional(self):
        orig = reference()
        self.convert(orig.resize((235, 176), NEAREST))
        np.testing.assert_array_equal(self.output(), np.asarray(orig))

    def test_offset(self):
        orig = reference()
        source = orig.resize((192, 144), NEAREST).crop((3, 5, 192, 144))
        report = self.convert(source)
        self.assertAlmostEqual(report["x_candidates"][0]["offset"], 5, delta=0.15)
        np.testing.assert_array_equal(self.output(), np.asarray(orig))

    def test_mild_blur(self):
        orig = reference()
        large = orig.resize((192, 144), NEAREST)
        image = large.filter(ImageFilter.GaussianBlur(0.7))
        report = self.convert(image)
        self.assertEqual(report["native_size"], list(orig.size))
        result = self.output().astype(float)
        visible = np.asarray(orig)[:, :, 3] == 255
        baseline = np.asarray(image.resize(orig.size, NEAREST)).astype(float)
        error = np.abs(result[visible, :3] - np.asarray(orig)[visible, :3]).mean()
        baseline_error = np.abs(baseline[visible, :3] - np.asarray(orig)[visible, :3]).mean()
        self.assertLessEqual(error, baseline_error + 1)

    def test_damaged_centers(self):
        orig = reference().convert("RGB")
        data = np.array(orig.resize((192, 144), NEAREST))
        data[4::8, 4::8] = [255, 0, 255]
        source = Image.fromarray(data)
        self.convert(source, "--size", "24x18")
        np.testing.assert_array_equal(self.output()[:, :, :3], np.asarray(orig))
        self.assertFalse(np.array_equal(np.asarray(source.resize(orig.size, NEAREST)), np.asarray(orig)))

    def test_mixed_grid(self):
        orig = reference().convert("RGB")
        mixed = Image.new("RGB", (192, 144))
        mixed.paste(orig.resize((192, 144), NEAREST).crop((0, 0, 192, 72)))
        mixed.paste(orig.resize((96, 72), NEAREST), (0, 72))
        mixed.paste(orig.resize((96, 72), NEAREST), (96, 72))
        report = self.convert(mixed, code=2)
        self.assertIn("x_regional_grid_disagreement", report["issues"])
        self.assertTrue((self.dest / "candidate.png").is_file())
        self.assertFalse((self.dest / "native.png").exists())

    def test_empty(self):
        report = self.convert(Image.new("RGBA", (64, 64)), code=2)
        self.assertIsNone(report["native_size"])
        self.assertFalse((self.dest / "candidate.png").exists())

    def test_aspect_mismatch(self):
        self.convert(reference(), "--size", "16x16", code=1)
        self.assertFalse(self.dest.exists())

    def test_pad_palette_binary(self):
        pal = self.root / "palette.png"
        Image.new("RGB", (1, 1), (10, 20, 30)).save(pal)
        self.convert(Image.new("RGBA", (32, 16), (90, 90, 150, 180)), "--size", "8x8",
                     "--fit", "pad", "--palette", pal, "--alpha", "binary")
        a = self.output()
        self.assertEqual(a.shape, (8, 8, 4))
        self.assertTrue((a[:2] == 0).all())
        self.assertTrue((a[2:6] == [10, 20, 30, 255]).all())

    def test_crop(self):
        self.convert(Image.new("RGBA", (32, 16), (11, 22, 33, 160)),
                     "--size", "8x8", "--fit", "crop")
        self.assertTrue((self.output() == [11, 22, 33, 160]).all())

    def test_herbalist_detail_points(self):
        example = Path(__file__).resolve().parents[1] / "examples/herbalist/input.png"
        with Image.open(example) as image:
            settings = ("--size", "96x96", "--alpha", "binary")
            self.convert(image, *settings)
            baseline = self.output()
            self.dest = self.root / "refined"
            report = self.convert(image, *settings, "--detail-point", "53,37",
                                  "--detail-point", "58,42")
        refined = self.output()
        np.testing.assert_array_equal(refined[:, :, 3], baseline[:, :, 3])
        unmarked = np.ones(baseline.shape[:2], dtype=bool)
        unmarked[37, 53] = unmarked[42, 58] = False
        np.testing.assert_array_equal(refined[unmarked], baseline[unmarked])

        # The left eye stroke is distinct from both its white and the right stroke.
        self.assertLess(int(refined[37, 53, :3].max()), 100)
        self.assertGreater(int(refined[37, 55, :3].min()), 175)
        self.assertLess(int(refined[37, 56, :3].max()), 100)
        # The dot at the mouth is slightly darker than adjacent skin.
        skin = refined[42, 57, :3].astype(float)
        mouth = refined[42, 58, :3].astype(float)
        contrast = (skin - mouth) @ [0.2126, 0.7152, 0.0722]
        self.assertGreater(contrast, 15)
        self.assertLess(contrast, 60)
        for detail in report["detail_points"]:
            self.assertGreater(len(detail["trials"]), 1)

    def test_palette_still_applies_at_detail_points(self):
        palette = self.root / "swatches.png"
        swatches = Image.new("RGB", (2, 1))
        swatches.putdata([(24, 20, 16), (255, 239, 213)])
        swatches.save(palette)
        image = Image.new("RGBA", (16, 16), (200, 170, 140, 180))
        image.paste((65, 48, 40, 180), (6, 0, 9, 16))
        self.convert(image, "--size", "2x2", "--detail-point", "0,0",
                     "--palette", palette)
        output = self.output()
        self.assertTrue((output[:, :, 3] == 180).all())
        self.assertTrue(set(map(tuple, output[:, :, :3].reshape(-1, 3))) <=
                        {(24, 20, 16), (255, 239, 213)})

    def test_detail_point_requires_target_coordinates(self):
        for settings in [(), ("--size", "12x9")]:
            with self.subTest(settings=settings):
                self.convert(reference(), *settings, "--detail-point", "12,0", code=1)
                self.assertFalse(self.dest.exists())

    def test_detail_point_ignores_near_transparent_rgb(self):
        image = Image.new("RGBA", (10, 10), (200, 200, 200, 255))
        image.paste((0, 0, 0, 255), (0, 0, 10, 2))
        image.putpixel((9, 9), (157, 157, 157, 1))
        self.convert(image, "--size", "1x1", "--alpha", "binary", "--detail-point", "0,0")
        self.assertTupleEqual(tuple(self.output()[0, 0]), (200, 200, 200, 255))

    def test_existing_output(self):
        self.dest.mkdir()
        self.convert(reference(), code=1)
        self.assertEqual(list(self.dest.iterdir()), [])
