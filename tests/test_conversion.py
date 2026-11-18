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

    def test_existing_output(self):
        self.dest.mkdir()
        self.convert(reference(), code=1)
        self.assertEqual(list(self.dest.iterdir()), [])
