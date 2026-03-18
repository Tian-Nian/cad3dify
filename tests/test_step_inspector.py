import tempfile
import unittest
from pathlib import Path

from cad3dify.step_inspector import export_orthographic_views, inspect_step, summarize_step


class StepInspectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sample_dir = Path(__file__).resolve().parents[1] / "sample_data"
        self.test_step = self.sample_dir / "test.stp"
        self.test2_step = self.sample_dir / "test2.stp"

    def test_summarize_step_returns_geometry_summary(self) -> None:
        summary = summarize_step(self.test_step)

        self.assertEqual(summary["solid_count"], 1)
        self.assertGreater(summary["bounding_box"]["size_mm"]["x"], 0)
        self.assertGreater(summary["bounding_box"]["size_mm"]["y"], 0)
        self.assertGreater(summary["bounding_box"]["size_mm"]["z"], 0)
        self.assertIn("orthographic_views", summary)
        self.assertIn("top", summary["orthographic_views"])

    def test_inspect_step_can_compare_two_models(self) -> None:
        result = inspect_step(self.test_step, compare_to=self.test2_step)

        self.assertIn("comparison", result)
        self.assertIn("bbox_size_delta_mm", result["comparison"])

    def test_export_orthographic_views_writes_svg_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            exported = export_orthographic_views(self.test_step, tmpdir)

            self.assertTrue(Path(exported["top"]).exists())
            self.assertTrue(Path(exported["front"]).exists())
            self.assertTrue(Path(exported["right"]).exists())


if __name__ == "__main__":
    unittest.main()