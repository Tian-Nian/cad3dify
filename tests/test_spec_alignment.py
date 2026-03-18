import unittest

from cad3dify.spec_alignment import build_contract, normalize_analysis_payload, validate_analysis_payload, validate_generated_code


class ValidateAnalysisPayloadTests(unittest.TestCase):
    def test_prismatic_support_contract_does_not_require_recess_seat(self) -> None:
        payload = {
            "drawing_summary": {
                "title": "Bearing Support Bracket",
                "description": "Rectangular support bracket with a base plate and a large central bore.",
            },
            "section_interpretation": {"datum_or_reference_face": "bottom"},
            "global_constraints": [],
            "modeling_sequence": [],
            "uncertainties": [],
            "views": [
                {
                    "name": "top_view",
                    "view_type": "top",
                    "contour_stack": [
                        {"order": 1, "role": "outer_silhouette", "shape": "rectangle", "width": 180.0, "height": 369.0},
                        {"order": 2, "role": "visible_opening", "diameter": 165.0},
                        {"order": 3, "role": "pattern_reference", "diameter": 130.1},
                    ],
                    "entities": [
                        {"id": "central_bore", "type": "circular_opening", "diameter": 165.0, "visible_on_face": "top_face"},
                        {"id": "hole_pattern_1", "type": "hole_pattern", "count": 4, "pattern_pcd": 130.1, "visible_on_face": "top_face"},
                    ],
                    "dimensions": [
                        {"label": "overall_width", "value": 180.0},
                        {"label": "overall_height", "value": 369.0},
                        {"label": "central_bore_diameter", "value": 165.0},
                        {"label": "pattern_pitch_circle_diameter", "value": 130.1},
                    ],
                },
                {
                    "name": "section_A-A",
                    "view_type": "section",
                    "axial_bands": [
                        {"band_id": "top", "band_role": "top_rim", "axial_start": 0.0, "axial_end": 24.0, "width": 180.0},
                        {"band_id": "wall", "band_role": "solid_wall", "axial_start": 24.0, "axial_end": 299.0, "width_estimate": 104.0},
                        {"band_id": "base", "band_role": "solid_wall", "axial_start": 319.0, "axial_end": 369.0, "width": 345.0},
                    ],
                    "entities": [
                        {"id": "bolt_holes", "type": "hole_pattern", "count": 4, "bolt_circle_diameter": 130.1, "start_face": "top"},
                    ],
                    "dimensions": [
                        {"label": "overall_height", "value": 369.0},
                        {"label": "top_flange_thickness", "value": 24.0},
                        {"label": "vertical_wall_width", "value": 104.0},
                        {"label": "base_flange_lower_height", "value": 50.0},
                    ],
                },
            ],
        }

        contract = build_contract(payload)
        issues = validate_analysis_payload(payload)

        self.assertEqual(contract["geometry_family"], "prismatic")
        self.assertEqual(contract["outer_diameter_flange"], 180.0)
        self.assertEqual(contract["outer_diameter_body"], 104.0)
        self.assertEqual(contract["lower_flange_height"], 50.0)
        self.assertNotIn("契约字段缺失: recess_seat_diameter。", issues)
        self.assertNotIn("契约字段缺失: outer_diameter_body。", issues)
        self.assertNotIn("契约字段缺失: lower_flange_height。", issues)

    def test_prismatic_mislabeled_top_view_is_flagged(self) -> None:
        payload = {
            "drawing_summary": {
                "title": "Bearing Support Bracket",
                "description": "Support bracket with base plate footprint, hidden pocket, and vertical plate bore.",
            },
            "section_interpretation": {"datum_or_reference_face": "bottom"},
            "global_constraints": [],
            "modeling_sequence": [],
            "uncertainties": [],
            "views": [
                {
                    "name": "top_view",
                    "view_type": "top",
                    "summary": "Rectangular standing plate with hidden base footprint below.",
                    "contour_stack": [
                        {"order": 1, "role": "outer_silhouette", "shape": "rectangle", "width": 180.0, "height": 369.0},
                        {"order": 2, "role": "visible_opening", "diameter": 165.0},
                        {"order": 3, "role": "pattern_reference", "diameter": 130.1},
                        {"order": 4, "role": "hidden_only", "shape": "rectangular_outline_dashed", "width": 305.0, "height": 44.0},
                    ],
                    "entities": [
                        {"id": "central_bore", "type": "circular_opening", "diameter": 165.0, "visible_on_face": "top_face"},
                        {"id": "hole_pattern_1", "type": "hole_pattern", "count": 4, "pattern_pcd": 130.1, "visible_on_face": "top_face"},
                    ],
                    "dimensions": [
                        {"label": "overall_width", "value": 180.0},
                        {"label": "overall_height", "value": 369.0},
                    ],
                },
                {
                    "name": "section_A-A",
                    "view_type": "section",
                    "axial_bands": [
                        {"band_id": "top", "band_role": "top_rim", "axial_start": 0.0, "axial_end": 24.0, "width": 180.0},
                        {"band_id": "wall", "band_role": "solid_wall", "axial_start": 24.0, "axial_end": 319.0, "width_estimate": 104.0},
                        {"band_id": "base", "band_role": "lower_flange", "axial_start": 319.0, "axial_end": 369.0, "width": 345.0},
                    ],
                    "entities": [
                        {"id": "bolt_holes", "type": "hole_pattern", "count": 4, "bolt_circle_diameter": 130.1, "start_face": "top"},
                    ],
                    "dimensions": [
                        {"label": "overall_height", "value": 369.0},
                        {"label": "top_flange_thickness", "value": 24.0},
                        {"label": "vertical_wall_width", "value": 104.0},
                        {"label": "base_flange_lower_height", "value": 50.0},
                    ],
                },
            ],
        }

        issues = validate_analysis_payload(payload)

        self.assertTrue(any("疑似把立板正视图误标为 top_view" in issue for issue in issues))
        self.assertTrue(any("更像立板正视图" in issue for issue in issues))

    def test_generic_section_labels_are_promoted_into_contract(self) -> None:
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
                        {"order": 1, "role": "outer_silhouette", "diameter": 100.0},
                        {"order": 2, "role": "pattern_reference", "diameter": 70.0},
                        {"order": 3, "role": "recess_boundary", "diameter": 24.0},
                        {"order": 4, "role": "visible_opening", "diameter": 10.0},
                    ],
                    "entities": [
                        {"id": "hole_pattern_1", "type": "hole_pattern", "count": 6, "pitch_circle_diameter": 70.0},
                        {"id": "central_bore", "type": "through_hole", "diameter": 10.0},
                    ],
                    "dimensions": [
                        {"label": "pattern_pitch_circle_diameter", "value": 70.0},
                    ],
                },
                {
                    "name": "section_right_side",
                    "view_type": "section",
                    "axial_bands": [
                        {"band_id": "band_1", "band_role": "solid_wall", "axial_start": 0.0, "axial_end": 10.0, "outer_diameter": 40.0, "inner_diameter": 10.0},
                        {"band_id": "band_2", "band_role": "middle_bore", "axial_start": 10.0, "axial_end": 20.0, "outer_diameter": 40.0, "inner_diameter": 10.0},
                        {"band_id": "band_3", "band_role": "solid_wall", "axial_start": 20.0, "axial_end": 30.0, "outer_diameter": 100.0, "inner_diameter": 24.0},
                    ],
                    "entities": [
                        {"id": "central_bore", "type": "through_hole", "diameter": 10.0},
                        {"id": "counterbore_right", "type": "counterbore", "diameter": 24.0, "depth": 10.0, "start_face": "right_face"},
                        {"id": "bolt_holes", "type": "hole_pattern", "count": 6, "bolt_circle_diameter": 70.0, "start_face": "top"},
                    ],
                    "dimensions": [
                        {"label": "overall_axial_length", "value": 30.0},
                        {"label": "outer_diameter_flange", "value": 100.0},
                        {"label": "outer_diameter_hub", "value": 40.0},
                        {"label": "central_bore_diameter", "value": 10.0},
                        {"label": "counterbore_diameter", "value": 24.0},
                        {"label": "axial_band_width_1", "value": 10.0},
                        {"label": "axial_band_width_2", "value": 10.0},
                        {"label": "axial_band_width_3", "value": 10.0},
                        {"label": "hole_pattern_pcd", "value": 70.0},
                    ],
                },
            ],
        }

        normalized = normalize_analysis_payload(payload)
        contract = build_contract(normalized)
        issues = validate_analysis_payload(normalized)

        self.assertEqual(contract["total_height"], 30.0)
        self.assertEqual(contract["outer_diameter_body"], 40.0)
        self.assertEqual(contract["recess_seat_diameter"], 24.0)
        self.assertEqual(contract["lower_flange_height"], 10.0)
        self.assertEqual(contract["middle_body_height"], 10.0)
        self.assertEqual(contract["upper_flange_height"], 10.0)
        self.assertNotIn("契约字段缺失: total_height。", issues)
        self.assertNotIn("契约字段缺失: upper_flange_height。", issues)
        self.assertNotIn("顶视可见上开口直径与剖视上台阶孔直径不一致。", issues)

    def test_string_feature_placement_does_not_crash(self) -> None:
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
                    ],
                    "entities": [
                        {
                            "id": "bolt_hole_pattern",
                            "type": "hole_pattern",
                            "count": 12,
                            "visible_on_face": "recess_floor",
                            "feature_placement": "recess_floor",
                        }
                    ],
                    "dimensions": [],
                },
                {
                    "name": "section_A-A",
                    "view_type": "section",
                    "axial_bands": [],
                    "entities": [
                        {
                            "id": "bolt_holes",
                            "type": "hole_pattern",
                            "count": 12,
                            "bolt_circle_diameter": 115.0,
                            "start_face": "upper_step",
                        }
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 139.0},
                        {"label": "bolt_circle_diameter", "value": 115.0},
                    ],
                },
            ],
        }

        issues = validate_analysis_payload(payload)

        self.assertIsInstance(issues, list)

    def test_normalization_fills_hole_pattern_aliases_and_section_entity(self) -> None:
        payload = {
            "drawing_summary": {},
            "section_interpretation": {"notes": ["Section A-A does not intersect bolt hole axes directly"]},
            "global_constraints": [
                {"constraint": "bolt_circle_diameter", "value": 115.0},
                {"constraint": "hole_pattern_count", "value": 12},
            ],
            "modeling_sequence": [],
            "uncertainties": [],
            "views": [
                {
                    "name": "top_view",
                    "view_type": "top",
                    "contour_stack": [
                        {"order": 1, "role": "outer_silhouette", "diameter": 139.0},
                        {"order": 2, "role": "recess_boundary", "diameter": 115.0},
                        {"order": 4, "role": "visible_opening", "diameter": 105.0},
                    ],
                    "entities": [
                        {
                            "id": "bolt_hole_pattern",
                            "type": "hole_pattern",
                            "hole_count": 12,
                            "bolt_circle_diameter": 115.0,
                            "visible_on_face": "recess_floor",
                        },
                        {"id": "upper_opening", "type": "counterbore", "diameter": 105.0},
                        {"id": "central_bore", "type": "through_hole", "diameter": 99.0},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 139.0},
                        {"label": "inner_diameter_upper", "value": 105.0},
                        {"label": "inner_diameter_bore", "value": 99.0},
                        {"label": "bolt_circle_diameter", "value": 115.0},
                    ],
                },
                {
                    "name": "section_A-A",
                    "view_type": "section",
                    "axial_bands": [
                        {"band_id": "lower_flange", "band_role": "lower_flange", "axial_start": 0, "axial_end": 9, "outer_diameter": 139.0, "inner_diameter": 99.0},
                        {"band_id": "middle_body", "band_role": "middle_body", "axial_start": 9, "axial_end": 20, "outer_diameter": 129.0, "inner_diameter": 99.0},
                        {"band_id": "upper_rim", "band_role": "top_rim", "axial_start": 20, "axial_end": 28, "outer_diameter": 129.0, "inner_diameter": 105.0},
                    ],
                    "entities": [
                        {"id": "central_bore", "type": "through_hole", "diameter": 99.0},
                        {"id": "upper_recess", "type": "annular_recess", "outer_diameter": 115.0, "inner_diameter": 105.0, "floor_z": 20.0},
                        {"id": "recessed_hole_seat", "type": "annular_floor", "outer_diameter": 115.0, "inner_diameter": 105.0, "z_level": 20.0},
                        {"id": "fillet_inner", "type": "fillet", "radius": 2.0},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 139.0},
                        {"label": "outer_diameter_body", "value": 129.0},
                        {"label": "inner_diameter_upper", "value": 105.0},
                        {"label": "inner_diameter_bore", "value": 99.0},
                        {"label": "recess_seat_diameter", "value": 115.0},
                        {"label": "total_height", "value": 28.0},
                        {"label": "lower_flange_height", "value": 9.0},
                        {"label": "middle_body_height", "value": 11.0},
                        {"label": "upper_flange_height", "value": 8.0},
                    ],
                },
            ],
        }

        normalized = normalize_analysis_payload(payload)
        issues = validate_analysis_payload(normalized)
        section_entities = normalized["views"][1]["entities"]
        section_holes = next(entity for entity in section_entities if entity.get("id") == "bolt_holes")

        self.assertEqual(normalized["views"][0]["entities"][0]["count"], 12)
        self.assertEqual(section_holes["count"], 12)
        self.assertEqual(section_holes["bolt_circle_diameter"], 115.0)
        self.assertEqual(section_holes["start_face"], "upper_step")
        self.assertNotIn("契约字段缺失: hole_count。", issues)
        self.assertNotIn("剖视图缺少螺栓孔阵列实体。", issues)
        self.assertNotIn("顶视可见上开口直径与剖视上台阶孔直径不一致。", issues)

    def test_missing_pcd_with_explicit_uncertainty_is_non_blocking(self) -> None:
        payload = {
            "drawing_summary": {},
            "section_interpretation": {},
            "global_constraints": [],
            "modeling_sequence": [],
            "uncertainties": [
                {
                    "item": "bolt_circle_diameter",
                    "reason": "PCD not explicitly dimensioned in the drawing",
                }
            ],
            "views": [
                {
                    "name": "top_view",
                    "view_type": "top",
                    "contour_stack": [
                        {"order": 1, "role": "outer_silhouette", "diameter": 139.0},
                        {"order": 4, "role": "visible_opening", "diameter": 105.0},
                    ],
                    "entities": [
                        {"id": "bolt_hole_pattern", "type": "hole_pattern", "count": 12},
                        {"id": "upper_opening", "type": "counterbore", "diameter": 129.0},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 139.0},
                        {"label": "inner_diameter_upper", "value": 105.0},
                    ],
                },
                {
                    "name": "section_A-A",
                    "view_type": "section",
                    "axial_bands": [
                        {"band_id": "lower_flange", "band_role": "lower_flange", "axial_start": 0, "axial_end": 9, "outer_diameter": 139.0, "inner_diameter": 99.0},
                        {"band_id": "middle_body", "band_role": "middle_body", "axial_start": 9, "axial_end": 20, "outer_diameter": 129.0, "inner_diameter": 99.0},
                        {"band_id": "upper_rim", "band_role": "top_rim", "axial_start": 20, "axial_end": 28, "outer_diameter": 129.0, "inner_diameter": 105.0},
                    ],
                    "entities": [
                        {"id": "central_bore", "type": "through_hole", "diameter": 99.0},
                        {"id": "recessed_hole_seat", "type": "annular_floor", "outer_diameter": 115.0, "inner_diameter": 105.0, "z_level": 20.0},
                        {"id": "fillet_inner", "type": "fillet", "radius": 2.0},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 139.0},
                        {"label": "outer_diameter_body", "value": 129.0},
                        {"label": "inner_diameter_upper", "value": 105.0},
                        {"label": "inner_diameter_bore", "value": 99.0},
                        {"label": "recess_seat_diameter", "value": 115.0},
                        {"label": "total_height", "value": 28.0},
                        {"label": "lower_flange_height", "value": 9.0},
                        {"label": "middle_body_height", "value": 11.0},
                        {"label": "upper_flange_height", "value": 8.0},
                    ],
                },
            ],
        }

        issues = validate_analysis_payload(payload)

        self.assertNotIn("契约字段缺失: bolt_circle_diameter。", issues)
        self.assertNotIn("顶视可见上开口直径与剖视上台阶孔直径不一致。", issues)

    def test_stepped_opening_diameter_ambiguity_is_non_blocking_when_both_levels_exist(self) -> None:
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
                        {"order": 3, "role": "recess_boundary", "diameter": 115.0},
                        {"order": 4, "role": "visible_opening", "diameter": 105.0},
                    ],
                    "entities": [
                        {"id": "upper_opening", "type": "counterbore", "diameter": 105.0},
                        {"id": "bolt_hole_pattern", "type": "hole_pattern", "count": 12, "bolt_circle_diameter": 115.0},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 139.0},
                        {"label": "inner_diameter_upper", "value": 115.0},
                    ],
                },
                {
                    "name": "section_A-A",
                    "view_type": "section",
                    "axial_bands": [
                        {"band_id": "lower_flange", "band_role": "lower_flange", "axial_start": 0, "axial_end": 9, "outer_diameter": 139.0, "inner_diameter": 99.0},
                        {"band_id": "middle_body", "band_role": "middle_body", "axial_start": 9, "axial_end": 20, "outer_diameter": 129.0, "inner_diameter": 99.0},
                        {"band_id": "upper_rim", "band_role": "top_rim", "axial_start": 20, "axial_end": 28, "outer_diameter": 129.0, "inner_diameter": 115.0},
                    ],
                    "entities": [
                        {"id": "recessed_hole_seat", "type": "annular_floor", "outer_diameter": 115.0, "inner_diameter": 105.0, "z_level": 20.0},
                        {"id": "upper_recess", "type": "annular_recess", "outer_diameter": 115.0, "inner_diameter": 105.0, "floor_z": 20.0},
                        {"id": "fillet_inner", "type": "fillet", "radius": 2.0},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 139.0},
                        {"label": "outer_diameter_body", "value": 129.0},
                        {"label": "inner_diameter_upper", "value": 115.0},
                        {"label": "inner_diameter_bore", "value": 99.0},
                        {"label": "recess_seat_diameter", "value": 105.0},
                        {"label": "total_height", "value": 28.0},
                        {"label": "lower_flange_height", "value": 9.0},
                        {"label": "middle_body_height", "value": 11.0},
                        {"label": "upper_flange_height", "value": 8.0},
                    ],
                },
            ],
        }

        issues = validate_analysis_payload(payload)

        self.assertNotIn("顶视可见上开口直径与剖视上台阶孔直径不一致。", issues)

    def test_build_contract_accepts_recess_seat_aliases_from_upper_recess_and_top_contours(self) -> None:
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
                        {"order": 2, "role": "pattern_reference", "diameter": 129.0},
                        {"order": 3, "role": "recess_seat_outer_boundary", "diameter": 115.0},
                        {"order": 4, "role": "recess_seat_inner_boundary", "diameter": 105.0},
                        {"order": 5, "role": "visible_opening", "diameter": 99.0},
                    ],
                    "entities": [
                        {"id": "bolt_hole_pattern", "type": "hole_pattern", "count": 12, "bolt_circle_diameter": 129.0, "visible_on_face": "recess_floor"},
                        {"id": "central_bore", "type": "through_hole", "diameter": 99.0, "visible_on_face": "recess_floor"},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 139.0},
                        {"label": "inner_diameter_bore", "value": 99.0},
                    ],
                },
                {
                    "name": "section_A-A",
                    "view_type": "section",
                    "axial_bands": [
                        {"band_id": "lower_flange", "band_role": "lower_flange", "axial_start": 0, "axial_end": 9, "outer_diameter": 139.0, "inner_diameter": 99.0},
                        {"band_id": "middle_body", "band_role": "middle_body", "axial_start": 9, "axial_end": 17, "outer_diameter": 115.0, "inner_diameter": 99.0},
                        {"band_id": "upper_rim", "band_role": "top_rim", "axial_start": 17, "axial_end": 28, "outer_diameter": 139.0, "inner_diameter": 139.0},
                    ],
                    "entities": [
                        {
                            "id": "upper_recess",
                            "type": "annular_recess",
                            "floor_z": 17.0,
                            "dimensions": {
                                "upper_opening_diameter_mm": 139.0,
                                "seat_outer_diameter_mm": 115.0,
                                "seat_inner_diameter_mm": 105.0,
                                "depth_mm": 11.0,
                            },
                        },
                        {"id": "bolt_holes", "type": "hole_pattern", "count": 12, "bolt_circle_diameter": 129.0, "start_face": "recess_floor", "axial_layer": "upper_flange_solid"},
                        {"id": "central_bore", "type": "through_hole", "diameter": 99.0},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 139.0},
                        {"label": "outer_diameter_body", "value": 115.0},
                        {"label": "inner_diameter_bore", "value": 99.0},
                        {"label": "total_height", "value": 28.0},
                        {"label": "lower_flange_height", "value": 9.0},
                        {"label": "middle_body_height", "value": 8.0},
                        {"label": "upper_flange_height", "value": 11.0},
                    ],
                },
            ],
        }

        contract = build_contract(payload)
        issues = validate_analysis_payload(payload)

        self.assertEqual(contract["recess_seat_diameter"], 115.0)
        self.assertEqual(contract["upper_opening_diameter"], 139.0)
        self.assertNotIn("契约字段缺失: recess_seat_diameter。", issues)

    def test_pattern_reference_pcd_and_upper_step_visibility_constraints(self) -> None:
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
                        {"order": 3, "role": "recess_boundary", "diameter": 125.0},
                        {"order": 4, "role": "pattern_reference", "diameter": 115.0},
                        {"order": 5, "role": "visible_opening", "diameter": 99.0},
                    ],
                    "entities": [
                        {"id": "bolt_hole_pattern", "type": "hole_pattern", "count": 12, "visible_on_face": "top_face"},
                        {"id": "upper_opening", "type": "counterbore", "diameter": 129.0},
                        {"id": "central_bore", "type": "through_hole", "diameter": 99.0},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 139.0},
                        {"label": "inner_diameter_upper", "value": 129.0},
                        {"label": "recess_seat_diameter", "value": 125.0},
                        {"label": "inner_diameter_bore", "value": 99.0},
                    ],
                },
                {
                    "name": "section_A-A",
                    "view_type": "section",
                    "axial_bands": [
                        {"band_id": "lower_flange", "band_role": "lower_flange", "axial_start": 0, "axial_end": 9, "outer_diameter": 139.0, "inner_diameter": 105.0},
                        {"band_id": "middle_body", "band_role": "middle_body", "axial_start": 9, "axial_end": 17, "outer_diameter": 139.0, "inner_diameter": 99.0},
                        {"band_id": "upper_rim", "band_role": "top_rim", "axial_start": 17, "axial_end": 28, "outer_diameter": 139.0, "inner_diameter": 129.0},
                    ],
                    "entities": [
                        {"id": "recessed_hole_seat", "type": "annular_floor", "outer_diameter": 115.0, "inner_diameter": 99.0, "z_level": 17.0},
                        {"id": "bolt_holes", "type": "hole_pattern", "count": 12, "start_face": "upper_step"},
                        {"id": "fillet_inner", "type": "fillet", "radius": 2.0},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 139.0},
                        {"label": "outer_diameter_body", "value": 139.0},
                        {"label": "inner_diameter_upper", "value": 129.0},
                        {"label": "recess_seat_diameter", "value": 115.0},
                        {"label": "inner_diameter_bore", "value": 99.0},
                        {"label": "total_height", "value": 28.0},
                        {"label": "lower_flange_height", "value": 9.0},
                        {"label": "middle_body_height", "value": 8.0},
                        {"label": "upper_flange_height", "value": 11.0},
                    ],
                },
            ],
        }

        issues = validate_analysis_payload(payload)

        self.assertIn("剖视已说明孔从凹台阶面起孔，但顶视仍把孔可见面写成 top_face。", issues)
        self.assertIn("孔阵列 PCD 被误写成凹台阶座面边界直径。", issues)

        payload["views"][0]["entities"][0]["visible_on_face"] = "recess_floor"
        payload["views"][1]["entities"][0]["outer_diameter"] = 125.0
        payload["views"][1]["dimensions"][3]["value"] = 125.0
        issues = validate_analysis_payload(payload)

        self.assertNotIn("剖视已说明孔从凹台阶面起孔，但顶视仍把孔可见面写成 top_face。", issues)
        self.assertNotIn("孔阵列 PCD 被误写成凹台阶座面边界直径。", issues)

    def test_validate_generated_code_flags_undefined_tagged_workplane(self) -> None:
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
                    "contour_stack": [{"order": 1, "role": "outer_silhouette", "diameter": 10.0}],
                    "entities": [
                        {"id": "upper_opening", "type": "circle", "diameter": 8.0},
                        {"id": "bolt_hole_pattern", "type": "hole_pattern", "count": 2, "bolt_circle_diameter": 6.0},
                        {"id": "central_bore", "type": "circle", "diameter": 4.0},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 10.0},
                        {"label": "inner_diameter_upper", "value": 8.0},
                        {"label": "inner_diameter_bore", "value": 4.0},
                        {"label": "bolt_circle_diameter", "value": 6.0},
                    ],
                },
                {
                    "name": "section_A-A",
                    "view_type": "section",
                    "axial_bands": [
                        {"band_id": "lower_flange", "band_role": "lower_flange", "axial_start": 0.0, "axial_end": 2.0, "outer_diameter": 10.0, "inner_diameter": 4.0},
                        {"band_id": "middle_body", "band_role": "middle_body", "axial_start": 2.0, "axial_end": 4.0, "outer_diameter": 8.0, "inner_diameter": 4.0},
                        {"band_id": "upper_rim", "band_role": "top_rim", "axial_start": 4.0, "axial_end": 6.0, "outer_diameter": 10.0, "inner_diameter": 8.0},
                    ],
                    "entities": [
                        {"id": "central_bore", "type": "through_hole", "diameter": 4.0},
                        {"id": "bolt_holes", "type": "hole_pattern", "count": 2, "bolt_circle_diameter": 6.0, "start_face": "bottom"},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 10.0},
                        {"label": "outer_diameter_body", "value": 8.0},
                        {"label": "inner_diameter_upper", "value": 8.0},
                        {"label": "inner_diameter_bore", "value": 4.0},
                        {"label": "recess_seat_diameter", "value": 8.0},
                        {"label": "total_height", "value": 6.0},
                        {"label": "lower_flange_height", "value": 2.0},
                        {"label": "middle_body_height", "value": 2.0},
                        {"label": "upper_flange_height", "value": 2.0},
                    ],
                },
            ],
        }
        code = """
import cadquery as cq
from cadquery import exporters

result = cq.Workplane(\"XY\").circle(5.0).extrude(6.0)
result = result.workplaneFromTagged(\"base\")
exporters.export(result, \"out.step\")
"""

        issues = validate_generated_code(code, payload)

        self.assertIn("代码引用了未定义的 tagged workplane: base。", issues)

    def test_validate_generated_code_flags_cutblind_without_solid(self) -> None:
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
                    "contour_stack": [{"order": 1, "role": "outer_silhouette", "diameter": 10.0}],
                    "entities": [
                        {"id": "upper_opening", "type": "circle", "diameter": 8.0},
                        {"id": "central_bore", "type": "circle", "diameter": 4.0},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 10.0},
                        {"label": "inner_diameter_upper", "value": 8.0},
                        {"label": "inner_diameter_bore", "value": 4.0},
                    ],
                },
                {
                    "name": "section_A-A",
                    "view_type": "section",
                    "axial_bands": [
                        {"band_id": "lower_flange", "band_role": "lower_flange", "axial_start": 0.0, "axial_end": 2.0, "outer_diameter": 10.0, "inner_diameter": 4.0},
                        {"band_id": "middle_body", "band_role": "middle_body", "axial_start": 2.0, "axial_end": 4.0, "outer_diameter": 8.0, "inner_diameter": 4.0},
                        {"band_id": "upper_rim", "band_role": "top_rim", "axial_start": 4.0, "axial_end": 6.0, "outer_diameter": 10.0, "inner_diameter": 8.0},
                    ],
                    "entities": [
                        {"id": "central_bore", "type": "through_hole", "diameter": 4.0},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 10.0},
                        {"label": "outer_diameter_body", "value": 8.0},
                        {"label": "inner_diameter_upper", "value": 8.0},
                        {"label": "inner_diameter_bore", "value": 4.0},
                        {"label": "recess_seat_diameter", "value": 8.0},
                        {"label": "total_height", "value": 6.0},
                        {"label": "lower_flange_height", "value": 2.0},
                        {"label": "middle_body_height", "value": 2.0},
                        {"label": "upper_flange_height", "value": 2.0},
                    ],
                },
            ],
        }
        code = """
import cadquery as cq
from cadquery import exporters

result = cq.Workplane(\"XY\").box(10, 10, 6)
result = (
    cq.Workplane(\"XY\")
    .workplane(offset=6)
    .circle(4)
    .cutBlind(-2)
)
exporters.export(result, \"out.step\")
"""

        issues = validate_generated_code(code, payload)

        self.assertIn("代码在全新 Workplane 上直接调用 cutBlind/cutThruAll，CadQuery 没有可切削的 solid。", issues)

    def test_validate_generated_code_does_not_false_positive_on_face_attached_cut(self) -> None:
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
                    "contour_stack": [{"order": 1, "role": "outer_silhouette", "diameter": 10.0}],
                    "entities": [
                        {"id": "upper_opening", "type": "circle", "diameter": 8.0},
                        {"id": "central_bore", "type": "circle", "diameter": 4.0},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 10.0},
                        {"label": "inner_diameter_upper", "value": 8.0},
                        {"label": "inner_diameter_bore", "value": 4.0},
                    ],
                },
                {
                    "name": "section_A-A",
                    "view_type": "section",
                    "axial_bands": [
                        {"band_id": "lower_flange", "band_role": "lower_flange", "axial_start": 0.0, "axial_end": 2.0, "outer_diameter": 10.0, "inner_diameter": 4.0},
                        {"band_id": "middle_body", "band_role": "middle_body", "axial_start": 2.0, "axial_end": 4.0, "outer_diameter": 8.0, "inner_diameter": 4.0},
                        {"band_id": "upper_rim", "band_role": "top_rim", "axial_start": 4.0, "axial_end": 6.0, "outer_diameter": 10.0, "inner_diameter": 8.0},
                    ],
                    "entities": [
                        {"id": "central_bore", "type": "through_hole", "diameter": 4.0},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 10.0},
                        {"label": "outer_diameter_body", "value": 8.0},
                        {"label": "inner_diameter_upper", "value": 8.0},
                        {"label": "inner_diameter_bore", "value": 4.0},
                        {"label": "recess_seat_diameter", "value": 8.0},
                        {"label": "total_height", "value": 6.0},
                        {"label": "lower_flange_height", "value": 2.0},
                        {"label": "middle_body_height", "value": 2.0},
                        {"label": "upper_flange_height", "value": 2.0},
                    ],
                },
            ],
        }
        code = """
import cadquery as cq
from cadquery import exporters

result = cq.Workplane(\"XY\").box(10, 10, 6)
result = (
    result
    .faces(\">Z\")
    .workplane()
    .circle(2)
    .cutBlind(-2)
)
exporters.export(result, \"out.step\")
"""

        issues = validate_generated_code(code, payload)

        self.assertNotIn("代码在全新 Workplane 上直接调用 cutBlind/cutThruAll，CadQuery 没有可切削的 solid。", issues)

    def test_validate_generated_code_flags_unsupported_loftcombine_keyword(self) -> None:
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
                    "contour_stack": [],
                    "entities": [],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 180.0},
                        {"label": "inner_diameter_upper", "value": 165.0},
                        {"label": "bolt_circle_diameter", "value": 130.1},
                    ],
                },
                {
                    "name": "section_A-A",
                    "view_type": "section",
                    "axial_bands": [
                        {
                            "band_id": "lower_flange",
                            "band_role": "lower_flange",
                            "axial_start": 0,
                            "axial_end": 50,
                            "outer_diameter": 180.0,
                            "inner_diameter": 165.0,
                        },
                        {
                            "band_id": "middle_body",
                            "band_role": "middle_body",
                            "axial_start": 50,
                            "axial_end": 325,
                            "outer_diameter": 104.0,
                            "inner_diameter": 165.0,
                        },
                    ],
                    "entities": [
                        {"id": "bolt_holes", "type": "hole_pattern", "count": 4, "bolt_circle_diameter": 130.1},
                    ],
                    "dimensions": [
                        {"label": "outer_diameter_flange", "value": 180.0},
                        {"label": "outer_diameter_body", "value": 104.0},
                        {"label": "inner_diameter_upper", "value": 165.0},
                        {"label": "inner_diameter_bore", "value": 165.0},
                        {"label": "total_height", "value": 369.0},
                        {"label": "lower_flange_height", "value": 50.0},
                        {"label": "middle_body_height", "value": 275.0},
                    ],
                },
            ],
        }
        code = """
import cadquery as cq

result = cq.Workplane("XY").box(180.0, 104.0, 50.0)
transition = cq.Workplane("XY").rect(180.0, 24.0).loft(loftCombine=True, ruled=True)
cq.exporters.export(result, "output.step")
"""

        issues = validate_generated_code(code, payload)

        self.assertIn("代码使用了当前 CadQuery 环境不支持的 loftCombine 参数。", issues)


if __name__ == "__main__":
    unittest.main()