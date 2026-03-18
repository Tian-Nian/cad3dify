import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cad3dify.pipeline import _analysis_documents_text_from_payload, _analysis_issue_guidance, _execution_failure_guidance, _format_step_comparison_feedback, _merge_analysis_with_fallback, _static_code_validation_guidance, initialize_workflow, run_analysis_stage, run_execution_stage, run_generation_stage


class AnalysisDocumentsTextTests(unittest.TestCase):
    def test_includes_normalized_contract_with_resolved_recess_seat(self) -> None:
        payload = {
            "drawing_summary": {},
            "section_interpretation": {},
            "global_constraints": [],
            "modeling_sequence": [],
            "uncertainties": [],
            "views": [
                {
                    "name": "top_view",
                    "view_type": "top",
                    "contour_stack": [
                        {"order": 1, "role": "outer_silhouette", "diameter": 139.0},
                        {"order": 2, "role": "visible_opening", "diameter": 129.0},
                        {"order": 3, "role": "pattern_reference", "diameter": 115.0},
                        {"order": 4, "role": "recess_boundary", "diameter": 105.0},
                        {"order": 5, "role": "visible_opening", "diameter": 99.0},
                    ],
                    "entities": [
                        {"id": "upper_opening", "type": "circle", "diameter": 129.0, "visible_on_face": "top_face"},
                        {
                            "id": "bolt_hole_pattern",
                            "type": "hole_pattern",
                            "count": 12,
                            "bolt_circle_diameter": 115.0,
                            "visible_on_face": "recess_floor",
                            "feature_placement": {"start_face": "recess_floor"},
                        },
                        {"id": "central_bore", "type": "circle", "diameter": 99.0, "visible_on_face": "internal_floor"},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 139.0},
                        {"label": "inner_diameter_upper", "value": 129.0},
                        {"label": "bolt_circle_diameter", "value": 115.0},
                        {"label": "recess_seat_diameter", "value": 105.0},
                        {"label": "inner_diameter_bore", "value": 99.0},
                    ],
                },
                {
                    "name": "section_A-A",
                    "view_type": "section",
                    "axial_bands": [
                        {"band_id": "lower_flange", "band_role": "lower_flange", "axial_start": 0, "axial_end": 9, "outer_diameter": 139.0, "inner_diameter": 99.0},
                        {"band_id": "middle_body", "band_role": "middle_body", "axial_start": 9, "axial_end": 17, "outer_diameter": 115.0, "inner_diameter": 99.0},
                        {"band_id": "upper_rim", "band_role": "top_rim", "axial_start": 17, "axial_end": 28, "outer_diameter": 139.0, "inner_diameter": 129.0},
                    ],
                    "entities": [
                        {"id": "fillet_inner", "type": "fillet", "radius": 2.0},
                        {"id": "central_bore", "type": "through_hole", "diameter": 99.0},
                        {"id": "bolt_holes", "type": "threaded_hole_pattern", "count": 12, "bolt_circle_diameter": 115.0, "start_face": "recessed_hole_seat"},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 139.0},
                        {"label": "outer_diameter_body", "value": 115.0},
                        {"label": "inner_diameter_upper", "value": 129.0},
                        {"label": "recess_seat_diameter", "value": 105.0},
                        {"label": "inner_diameter_bore", "value": 99.0},
                        {"label": "total_height", "value": 28.0},
                        {"label": "lower_flange_height", "value": 9.0},
                        {"label": "middle_body_height", "value": 8.0},
                        {"label": "upper_flange_height", "value": 11.0},
                    ],
                },
            ],
        }

        text = _analysis_documents_text_from_payload(payload)

        self.assertIn("## normalized_contract.json", text)
        self.assertIn('"recess_seat_diameter": 125.0', text)

    def test_merge_analysis_with_fallback_dedupes_dict_uncertainties(self) -> None:
        primary = {
            "drawing_summary": {},
            "section_interpretation": {},
            "views": [],
            "global_constraints": [],
            "modeling_sequence": [],
            "uncertainties": {"source": "primary", "note": "a"},
        }
        fallback = {
            "drawing_summary": {},
            "section_interpretation": {},
            "views": [],
            "global_constraints": [],
            "modeling_sequence": [],
            "uncertainties": [
                {"source": "primary", "note": "a"},
                {"source": "fallback", "note": "b"},
            ],
        }

        merged = _merge_analysis_with_fallback(primary, fallback)

        self.assertEqual(
            merged["uncertainties"],
            [
                {"source": "primary", "note": "a"},
                {"source": "fallback", "note": "b"},
            ],
        )


class WorkflowAutomationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_root = Path(__file__).resolve().parents[1]
        self.sample_dir = self.project_root / "sample_data"

    def test_static_code_validation_guidance_mentions_boolean_and_fillet_repairs(self) -> None:
        guidance = _static_code_validation_guidance(
            [
                "代码在全新 Workplane 上直接调用 cutBlind/cutThruAll，CadQuery 没有可切削的 solid。",
                "代码把必需的内圆角放进 try/except 后静默跳过，闭环执行风险过高。",
            ]
        )

        self.assertIn("Structured static repair guidance", guidance)
        self.assertIn("start from the owning solid face", guidance)
        self.assertIn("Remove silent `try/except ... pass`", guidance)

    def test_analysis_issue_guidance_summarizes_current_problem_types(self) -> None:
        guidance = _analysis_issue_guidance(
            [
                "契约字段缺失: recess_seat_diameter。",
                "顶视图缺少螺栓孔阵列实体。",
                "孔阵列 PCD 被误写成凹台阶座面边界直径。",
                "顶视已说明孔图元来自下层可见面，但剖视仍把孔起始面写成 top。",
            ]
        )

        self.assertIn("Structured analysis repair guidance", guidance)
        self.assertIn("Recover missing contract fields", guidance)
        self.assertIn("pattern-reference dimensions separate from material-boundary dimensions", guidance)
        self.assertIn("visibility provenance separate from the true owning or start face", guidance)

    def test_initialize_workflow_auto_detects_reference_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = initialize_workflow(
                image_filepath=str(self.sample_dir / "test.jpg"),
                workspace_dir=tmpdir,
                model_type="custom",
            )

            metadata = json.loads((workspace / "workflow.json").read_text(encoding="utf-8"))

            self.assertEqual(metadata["original_source_image"], str((self.sample_dir / "test.jpg").resolve()))
            self.assertEqual(metadata["reference_step"], str((self.sample_dir / "test.stp").resolve()))
            self.assertTrue((workspace / "input.jpg").exists())

    def test_run_execution_stage_uses_step_comparison_to_trigger_auto_refine(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            metadata = {
                "model_type": "custom",
                "source_image": str((self.sample_dir / "test.jpg").resolve()),
                "output_filename": "output.step",
                "reference_step": str((self.sample_dir / "test.stp").resolve()),
            }
            (workspace / "workflow.json").write_text(json.dumps(metadata), encoding="utf-8")
            (workspace / "analysis.generated.json").write_text("{}\n", encoding="utf-8")

            initial_code = (
                'from pathlib import Path\n'
                'Path("output_v01.step").write_text("v1", encoding="utf-8")\n'
            )
            refined_code = (
                'from pathlib import Path\n'
                'Path("output_v02.step").write_text("v2", encoding="utf-8")\n'
            )
            (workspace / "model_v01.generated.py").write_text(initial_code, encoding="utf-8")

            orthographic_views = {
                "top": {"circular_edges": []},
                "front": {"circular_edges": []},
                "right": {"circular_edges": []},
            }
            comparison_mismatch = {
                "summary": {
                    "source": str((workspace / "output_v01.step").resolve()),
                    "orthographic_views": orthographic_views,
                },
                "reference_summary": {
                    "source": str((self.sample_dir / "test.stp").resolve()),
                    "orthographic_views": orthographic_views,
                },
                "comparison": {
                    "bbox_size_delta_mm": {"x": 1.0, "y": 0.0, "z": 0.0},
                    "volume_delta_mm3": -10.0,
                    "solid_count_delta": 0,
                    "face_type_delta": {"cylinder": -2},
                    "edge_type_delta": {"circle": -4},
                },
            }
            comparison_match = {
                "summary": {
                    "source": str((workspace / "output_v02.step").resolve()),
                    "orthographic_views": orthographic_views,
                },
                "reference_summary": {
                    "source": str((self.sample_dir / "test.stp").resolve()),
                    "orthographic_views": orthographic_views,
                },
                "comparison": {
                    "bbox_size_delta_mm": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "volume_delta_mm3": 0.0,
                    "solid_count_delta": 0,
                    "face_type_delta": {},
                    "edge_type_delta": {},
                },
            }

            feedback_calls: list[str] = []

            def fake_refine_code_from_feedback(
                workspace_path: Path,
                metadata: dict,
                analysis_payload: dict,
                current_code: str,
                feedback: str,
            ) -> str:
                feedback_calls.append(feedback)
                return refined_code

            def fake_persist_code_version(workspace_path: Path, version: int, code: str, analysis_payload: dict) -> Path:
                generated_path = workspace_path / f"model_v{version:02d}.generated.py"
                review_path = workspace_path / f"model_v{version:02d}.py"
                generated_path.write_text(code, encoding="utf-8")
                review_path.write_text(code, encoding="utf-8")
                return review_path

            with patch("cad3dify.pipeline.validate_analysis_payload", return_value=[]), patch(
                "cad3dify.pipeline.inspect_step",
                side_effect=[comparison_mismatch, comparison_match],
            ) as inspect_mock, patch(
                "cad3dify.pipeline._refine_code_from_feedback",
                side_effect=fake_refine_code_from_feedback,
            ) as refine_mock, patch(
                "cad3dify.pipeline._persist_code_version",
                side_effect=fake_persist_code_version,
            ):
                result = run_execution_stage(str(workspace), max_auto_repairs=1)

            self.assertEqual(result, workspace / "output_v02.step")
            self.assertTrue((workspace / "output_v02.step").exists())
            self.assertTrue((workspace / "output.step").exists())
            self.assertTrue((workspace / "step_inspection_v01.json").exists())
            self.assertTrue((workspace / "step_inspection_v02.json").exists())
            self.assertEqual(inspect_mock.call_count, 2)
            self.assertEqual(refine_mock.call_count, 1)
            self.assertEqual(len(feedback_calls), 1)
            self.assertIn("## STEP comparison against reference", feedback_calls[0])
            self.assertIn("Bounding-box size mismatch on X axis", feedback_calls[0])

    def test_run_execution_stage_rolls_back_to_refine_stage_after_inline_repairs_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            metadata = {
                "model_type": "custom",
                "source_image": str((self.sample_dir / "test.jpg").resolve()),
                "output_filename": "output.step",
                "reference_step": str((self.sample_dir / "test.stp").resolve()),
            }
            (workspace / "workflow.json").write_text(json.dumps(metadata), encoding="utf-8")
            (workspace / "analysis.generated.json").write_text("{}\n", encoding="utf-8")

            initial_code = (
                'from pathlib import Path\n'
                'Path("output_v01.step").write_text("v1", encoding="utf-8")\n'
            )
            refined_stage_code = (
                'from pathlib import Path\n'
                'Path("output_v02.step").write_text("v2", encoding="utf-8")\n'
            )
            (workspace / "model_v01.generated.py").write_text(initial_code, encoding="utf-8")

            orthographic_views = {
                "top": {"circular_edges": []},
                "front": {"circular_edges": []},
                "right": {"circular_edges": []},
            }
            comparison_mismatch = {
                "summary": {
                    "source": str((workspace / "output_v01.step").resolve()),
                    "orthographic_views": orthographic_views,
                },
                "reference_summary": {
                    "source": str((self.sample_dir / "test.stp").resolve()),
                    "orthographic_views": orthographic_views,
                },
                "comparison": {
                    "bbox_size_delta_mm": {"x": 1.0, "y": 0.0, "z": 0.0},
                    "volume_delta_mm3": -10.0,
                    "solid_count_delta": 1,
                    "face_type_delta": {"cylinder": -2},
                    "edge_type_delta": {"circle": -4},
                },
            }
            comparison_match = {
                "summary": {
                    "source": str((workspace / "output_v02.step").resolve()),
                    "orthographic_views": orthographic_views,
                },
                "reference_summary": {
                    "source": str((self.sample_dir / "test.stp").resolve()),
                    "orthographic_views": orthographic_views,
                },
                "comparison": {
                    "bbox_size_delta_mm": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "volume_delta_mm3": 0.0,
                    "solid_count_delta": 0,
                    "face_type_delta": {},
                    "edge_type_delta": {},
                },
            }

            def fake_refine_stage(workspace_dir: str) -> Path:
                workspace_path = Path(workspace_dir)
                generated_path = workspace_path / "model_v02.generated.py"
                review_path = workspace_path / "model_v02.py"
                generated_path.write_text(refined_stage_code, encoding="utf-8")
                review_path.write_text(refined_stage_code, encoding="utf-8")
                return review_path

            with patch("cad3dify.pipeline.validate_analysis_payload", return_value=[]), patch(
                "cad3dify.pipeline.inspect_step",
                side_effect=[comparison_mismatch, comparison_match],
            ) as inspect_mock, patch(
                "cad3dify.pipeline.run_refinement_stage",
                side_effect=fake_refine_stage,
            ) as refine_stage_mock:
                result = run_execution_stage(str(workspace), max_auto_repairs=0, max_refinement_cycles=1)

            self.assertEqual(result, workspace / "output_v02.step")
            self.assertEqual(inspect_mock.call_count, 2)
            self.assertEqual(refine_stage_mock.call_count, 1)

    def test_execution_failure_guidance_mentions_loft_and_union_repairs(self) -> None:
        guidance = _execution_failure_guidance(
            """
            TypeError: Workplane.loft() got an unexpected keyword argument 'loftCombine'
            ValueError: Workplane object must have at least one solid on the stack to union!
            """,
            "chamfer_solid = bottom_wire.loft(loftCombine=True, ruled=True)\nresult = base.union(chamfer_solid)",
        )

        self.assertIn("Structured execution repair guidance", guidance)
        self.assertIn("loftCombine", guidance)
        self.assertIn("union()", guidance)

    def test_step_comparison_feedback_mentions_reference_axis_when_mismatched(self) -> None:
        feedback = _format_step_comparison_feedback(
            {
                "summary": {
                    "source": "generated.step",
                    "solid_count": 1,
                    "bounding_box": {"center_mm": {"x": 0.0, "y": 0.0, "z": 0.0}, "size_mm": {"x": 345.0, "y": 104.0, "z": 369.0}},
                    "faces": {"cylindrical_features": [{"dominant_axis": "X"}]},
                    "orthographic_views": {"top": {"circular_edges": []}, "front": {"circular_edges": []}, "right": {"circular_edges": []}},
                },
                "reference_summary": {
                    "source": "reference.step",
                    "solid_count": 1,
                    "bounding_box": {"center_mm": {"x": 0.0, "y": 10.0, "z": 0.0}, "size_mm": {"x": 345.0, "y": 369.0, "z": 104.0}},
                    "faces": {"cylindrical_features": [{"dominant_axis": "Y"}]},
                    "orthographic_views": {"top": {"circular_edges": []}, "front": {"circular_edges": []}, "right": {"circular_edges": []}},
                },
                "comparison": {
                    "bbox_size_delta_mm": {"x": 0.0, "y": -10.0, "z": 10.0},
                    "volume_delta_mm3": 5.0,
                    "solid_count_delta": 0,
                    "face_type_delta": {},
                    "edge_type_delta": {},
                },
            }
        )

        self.assertIn("Rebuild the main bore and hole operations along global Y", feedback)
        self.assertIn("coordinate-frame or envelope-construction bug", feedback)
        self.assertIn("X=345.0 mm, Y=369.0 mm, Z=104.0 mm", feedback)

    def test_run_analysis_stage_saves_full_analysis_and_normalized_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = initialize_workflow(
                image_filepath=str(self.sample_dir / "test2.jpg"),
                workspace_dir=tmpdir,
                model_type="custom",
            )

            analysis_payload = {
                "drawing_summary": {"title": "fallback"},
                "section_interpretation": {"hatched_regions_are_solid": True},
                "views": [
                    {
                        "name": "top_view",
                        "view_type": "top",
                        "summary": "top",
                        "contour_stack": [],
                        "entities": [],
                        "dimensions": [],
                        "cross_view_mapping": [],
                        "notes": [],
                    },
                    {
                        "name": "section_A-A",
                        "view_type": "section",
                        "summary": "section",
                        "axial_bands": [],
                        "entities": [],
                        "dimensions": [],
                        "cross_view_mapping": [],
                        "notes": [],
                    },
                ],
                "global_constraints": [],
                "modeling_sequence": [],
                "uncertainties": [],
            }

            with patch("cad3dify.pipeline.CadDrawingAnalyzerChain") as analyzer_chain_cls, patch(
                "cad3dify.pipeline.validate_analysis_payload", return_value=[]
            ):
                analyzer_chain_cls.return_value.invoke.return_value = {"result": analysis_payload}

                result_path = run_analysis_stage(str(workspace))

            payload = json.loads(result_path.read_text(encoding="utf-8"))
            normalized_contract = json.loads((workspace / "normalized_contract.json").read_text(encoding="utf-8"))

            self.assertEqual(result_path, workspace / "analysis.json")
            self.assertEqual(len(payload["views"]), 2)
            self.assertTrue(any(view.get("view_type") == "top" for view in payload["views"]))
            self.assertTrue(any(view.get("view_type") == "section" for view in payload["views"]))
            self.assertIsInstance(normalized_contract, dict)

    def test_run_analysis_stage_repairs_blocking_issues_before_returning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = initialize_workflow(
                image_filepath=str(self.sample_dir / "test2.jpg"),
                workspace_dir=tmpdir,
                model_type="custom",
            )

            analysis_payload = {
                "drawing_summary": {"title": "test2"},
                "section_interpretation": {"hatched_regions_are_solid": True},
                "views": [
                    {
                        "name": "top_view",
                        "view_type": "top",
                        "summary": "top",
                        "contour_stack": [],
                        "entities": [],
                        "dimensions": [],
                        "cross_view_mapping": [],
                        "notes": [],
                    },
                    {
                        "name": "section_A-A",
                        "view_type": "section",
                        "summary": "section",
                        "axial_bands": [],
                        "entities": [],
                        "dimensions": [],
                        "cross_view_mapping": [],
                        "notes": [],
                    },
                ],
                "global_constraints": [],
                "modeling_sequence": [],
                "uncertainties": [],
            }

            repaired_payload = dict(analysis_payload)
            repaired_payload["uncertainties"] = ["repaired"]

            with patch("cad3dify.pipeline.CadDrawingAnalyzerChain") as analyzer_chain_cls, patch(
                "cad3dify.pipeline.validate_analysis_payload",
                side_effect=[
                    ["契约字段缺失: outer_diameter_body。"],
                    [],
                ],
            ), patch(
                "cad3dify.pipeline._repair_analysis_until_aligned",
                return_value=repaired_payload,
            ) as repair_mock, patch(
                "cad3dify.pipeline.format_analysis_report",
                return_value="# Analysis Alignment Report\n\n## Issues\n- repaired\n",
            ):
                analyzer_chain_cls.return_value.invoke.return_value = {"result": analysis_payload}
                result_path = run_analysis_stage(str(workspace))

            self.assertEqual(result_path, workspace / "analysis.json")
            self.assertEqual(json.loads(result_path.read_text(encoding="utf-8"))["uncertainties"], ["repaired"])
            repair_mock.assert_called_once()

    def test_run_analysis_stage_raises_after_automatic_repair_if_blocking_issues_remain(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = initialize_workflow(
                image_filepath=str(self.sample_dir / "test2.jpg"),
                workspace_dir=tmpdir,
                model_type="custom",
            )

            analysis_payload = {
                "drawing_summary": {"title": "test2"},
                "section_interpretation": {"hatched_regions_are_solid": True},
                "views": [
                    {
                        "name": "top_view",
                        "view_type": "top",
                        "summary": "top",
                        "contour_stack": [],
                        "entities": [],
                        "dimensions": [],
                        "cross_view_mapping": [],
                        "notes": [],
                    },
                    {
                        "name": "section_A-A",
                        "view_type": "section",
                        "summary": "section",
                        "axial_bands": [],
                        "entities": [],
                        "dimensions": [],
                        "cross_view_mapping": [],
                        "notes": [],
                    },
                ],
                "global_constraints": [],
                "modeling_sequence": [],
                "uncertainties": [],
            }

            with patch("cad3dify.pipeline.CadDrawingAnalyzerChain") as analyzer_chain_cls, patch(
                "cad3dify.pipeline.validate_analysis_payload",
                side_effect=[
                    ["契约字段缺失: outer_diameter_body。"],
                    ["契约字段缺失: outer_diameter_body。"],
                ],
            ), patch(
                "cad3dify.pipeline._repair_analysis_until_aligned",
                return_value=analysis_payload,
            ), patch(
                "cad3dify.pipeline.format_analysis_report",
                return_value="# Analysis Alignment Report\n\n## Issues\n- 契约字段缺失: outer_diameter_body。\n",
            ):
                analyzer_chain_cls.return_value.invoke.return_value = {"result": analysis_payload}
                with self.assertRaises(ValueError) as exc_info:
                    run_analysis_stage(str(workspace))

            self.assertIn("Analysis JSON still failed alignment checks after automatic repair", str(exc_info.exception))

    def test_run_analysis_stage_retries_after_transient_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = initialize_workflow(
                image_filepath=str(self.sample_dir / "test2.jpg"),
                workspace_dir=tmpdir,
                model_type="custom",
            )

            analysis_payload = {
                "drawing_summary": {"title": "test2"},
                "section_interpretation": {"hatched_regions_are_solid": True},
                "views": [
                    {
                        "name": "top_view",
                        "view_type": "top",
                        "summary": "top",
                        "contour_stack": [],
                        "entities": [],
                        "dimensions": [],
                        "cross_view_mapping": [],
                        "notes": [],
                    },
                    {
                        "name": "section_A-A",
                        "view_type": "section",
                        "summary": "section",
                        "axial_bands": [],
                        "entities": [],
                        "dimensions": [],
                        "cross_view_mapping": [],
                        "notes": [],
                    },
                ],
                "global_constraints": [],
                "modeling_sequence": [],
                "uncertainties": [],
            }

            with patch("cad3dify.pipeline.CadDrawingAnalyzerChain") as analyzer_chain_cls, patch(
                "cad3dify.pipeline.validate_analysis_payload",
                return_value=[],
            ):
                analyzer_chain_cls.return_value.invoke.side_effect = [
                    RuntimeError("524 timeout"),
                    {"result": analysis_payload},
                ]

                result_path = run_analysis_stage(str(workspace))

            payload = json.loads(result_path.read_text(encoding="utf-8"))

            self.assertEqual(result_path, workspace / "analysis.json")
            self.assertEqual(payload["drawing_summary"]["title"], "test2")
            self.assertTrue(any(view.get("view_type") == "top" for view in payload["views"]))
            self.assertTrue(any(view.get("view_type") == "section" for view in payload["views"]))

    def test_run_analysis_stage_surfaces_exhausted_upstream_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = initialize_workflow(
                image_filepath=str(self.sample_dir / "test2.jpg"),
                workspace_dir=tmpdir,
                model_type="custom",
            )

            with patch("cad3dify.pipeline.CadDrawingAnalyzerChain") as analyzer_chain_cls, patch(
                "cad3dify.pipeline.time.sleep"
            ) as sleep_mock:
                analyzer_chain_cls.return_value.invoke.side_effect = [
                    RuntimeError("429 rate limit"),
                    RuntimeError("429 rate limit"),
                    RuntimeError("524 timeout"),
                ]

                with self.assertRaises(RuntimeError) as exc_info:
                    run_analysis_stage(str(workspace))

            self.assertIn("Full drawing analysis exhausted retries after repeated upstream/model errors", str(exc_info.exception))
            self.assertIn("524 timeout", str(exc_info.exception))
            self.assertEqual([call.args[0] for call in sleep_mock.call_args_list], [2.0, 4.0])

    def test_run_generation_stage_repairs_analysis_before_generating_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = initialize_workflow(
                image_filepath=str(self.sample_dir / "test2.jpg"),
                workspace_dir=tmpdir,
                model_type="custom",
            )

            invalid_payload = {
                "drawing_summary": {"title": "test2"},
                "section_interpretation": {"hatched_regions_are_solid": True},
                "views": [
                    {"name": "top_view", "view_type": "top", "summary": "top", "contour_stack": [], "entities": [], "dimensions": [], "cross_view_mapping": [], "notes": []},
                    {"name": "section_A-A", "view_type": "section", "summary": "section", "axial_bands": [], "entities": [], "dimensions": [], "cross_view_mapping": [], "notes": []},
                ],
                "global_constraints": [],
                "modeling_sequence": [],
                "uncertainties": [],
            }
            (workspace / "analysis.generated.json").write_text(json.dumps(invalid_payload), encoding="utf-8")

            repaired_payload = dict(invalid_payload)
            repaired_payload["uncertainties"] = ["aligned"]

            generated_code = 'from pathlib import Path\nPath("output.step").write_text("ok", encoding="utf-8")\n'

            with patch("cad3dify.pipeline._ensure_analysis_aligned", return_value=repaired_payload) as ensure_mock, patch(
                "cad3dify.pipeline.CadCodeFromJsonGeneratorChain"
            ) as generator_chain_cls, patch(
                "cad3dify.pipeline.validate_generated_code",
                return_value=[],
            ):
                generator_chain_cls.return_value.invoke.return_value = {"result": generated_code, "text": generated_code}

                result_path = run_generation_stage(str(workspace))

            self.assertTrue(result_path.exists())
            ensure_mock.assert_called_once()

    def test_run_analysis_stage_saves_chain_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = initialize_workflow(
                image_filepath=str(self.sample_dir / "test2.jpg"),
                workspace_dir=tmpdir,
                model_type="custom",
            )

            analysis_payload = {
                "drawing_summary": {"title": "test2"},
                "section_interpretation": {"hatched_regions_are_solid": True},
                "views": [
                    {
                        "name": "top_view",
                        "view_type": "top",
                        "summary": "top",
                        "contour_stack": [],
                        "entities": [],
                        "dimensions": [],
                        "cross_view_mapping": [],
                        "notes": [],
                    },
                    {
                        "name": "section_A-A",
                        "view_type": "section",
                        "summary": "section",
                        "axial_bands": [],
                        "entities": [],
                        "dimensions": [],
                        "cross_view_mapping": [],
                        "notes": [],
                    },
                ],
                "global_constraints": [],
                "modeling_sequence": [],
                "uncertainties": [],
            }

            with patch("cad3dify.pipeline.CadDrawingAnalyzerChain") as analyzer_chain_cls, patch(
                "cad3dify.pipeline.validate_analysis_payload",
                return_value=[],
            ):
                analyzer_chain_cls.return_value.invoke.return_value = {
                    "result": analysis_payload,
                    "text": json.dumps(analysis_payload, ensure_ascii=False),
                }

                run_analysis_stage(str(workspace))

            logs_dir = workspace / "chain_logs"
            log_files = sorted(logs_dir.glob("*.md"))

            self.assertTrue(log_files)
            first_log = log_files[0].read_text(encoding="utf-8")
            self.assertIn("## Inputs", first_log)
            self.assertIn("## Parsed Result", first_log)


if __name__ == "__main__":
    unittest.main()