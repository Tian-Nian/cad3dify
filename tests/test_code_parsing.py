import unittest

from cad3dify.v1.cad_code_generator import _parse_code


class ParseCodeTests(unittest.TestCase):
    def test_parse_code_accepts_markdown_fence(self) -> None:
        result = _parse_code({"text": "```python\nimport cadquery as cq\nresult = cq.Workplane(\"XY\")\n```"})
        self.assertIn("import cadquery as cq", result["result"])

    def test_parse_code_accepts_raw_python(self) -> None:
        raw = "import cadquery as cq\nfrom cadquery import exporters\nresult = cq.Workplane(\"XY\")\nexporters.export(result, \"x.step\")"
        result = _parse_code({"text": raw})
        self.assertEqual(result["result"], raw)

    def test_parse_code_extracts_code_after_prose(self) -> None:
        text = (
            "Here is the corrected program.\n\n"
            "import cadquery as cq\n"
            "from cadquery import exporters\n"
            "result = cq.Workplane(\"XY\").box(1, 1, 1)\n"
            "exporters.export(result, \"x.step\")"
        )

        result = _parse_code({"text": text})

        self.assertIn("import cadquery as cq", result["result"])
        self.assertNotIn("Here is the corrected program.", result["result"])

    def test_parse_code_rejects_explanatory_markdown_without_python(self) -> None:
        text = (
            "1. **Volume delta of -31183 mm³** - current model is missing significant material\n"
            "2. The flange needs more detail\n"
            "3. Add the missing rounds\n"
        )

        result = _parse_code({"text": text})

        self.assertIsNone(result["result"])


if __name__ == "__main__":
    unittest.main()