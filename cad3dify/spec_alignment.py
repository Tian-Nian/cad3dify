import ast
import copy
import json
import math
import re
from typing import Any


def _find_view(payload: dict[str, Any], view_type: str) -> dict[str, Any] | None:
    for view in payload.get("views", []):
        if view.get("view_type") == view_type:
            return view
    return None


def _find_entity(view: dict[str, Any] | None, entity_id: str) -> dict[str, Any] | None:
    if not view:
        return None
    for entity in view.get("entities", []):
        if not isinstance(entity, dict):
            continue
        if entity.get("id") == entity_id or entity.get("entity_id") == entity_id:
            return entity
    return None


def _find_entity_by_type(view: dict[str, Any] | None, *entity_types: str) -> dict[str, Any] | None:
    if not view:
        return None
    expected = set(entity_types)
    for entity in view.get("entities", []):
        if not isinstance(entity, dict):
            continue
        entity_type = entity.get("type") or entity.get("entity_type")
        if entity_type in expected:
            return entity
    return None


def _find_entities_by_type(view: dict[str, Any] | None, *entity_types: str) -> list[dict[str, Any]]:
    if not view:
        return []
    expected = set(entity_types)
    return [
        entity
        for entity in view.get("entities", [])
        if isinstance(entity, dict)
        if (entity.get("type") or entity.get("entity_type")) in expected
    ]


def _numeric_value(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _dict_get(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, dict) else default


def _first_numeric(*values: Any) -> float | None:
    for value in values:
        numeric = _numeric_value(value)
        if numeric is not None:
            return numeric
    return None


def _infer_geometry_family(
    payload: dict[str, Any],
    top_view: dict[str, Any] | None = None,
    section_view: dict[str, Any] | None = None,
) -> str:
    top_view = top_view or _find_view(payload, "top")
    section_view = section_view or _find_view(payload, "section")
    top_outer_contour = _find_contour(top_view, order=1, role="outer_silhouette")
    outer_shape = str(_dict_get(top_outer_contour, "shape", "")).lower()
    summary = _as_dict(payload.get("drawing_summary")) or {}
    summary_text = " ".join(str(value) for value in summary.values()).lower()

    if isinstance(_dict_get(top_outer_contour, "diameter"), (int, float)):
        return "axisymmetric"
    if outer_shape in {"rectangle", "rectangular_outline", "rectangular_outline_dashed"}:
        return "prismatic"
    if isinstance(_dict_get(top_outer_contour, "width"), (int, float)) or isinstance(_dict_get(top_outer_contour, "height"), (int, float)):
        return "prismatic"
    if any(keyword in summary_text for keyword in ("bracket", "support", "pillow block", "pedestal", "base plate", "rectangular")):
        return "prismatic"

    section_bands = section_view.get("axial_bands", []) if section_view else []
    if any(
        isinstance(_dict_get(band, "outer_diameter"), (int, float)) or isinstance(_dict_get(band, "inner_diameter"), (int, float))
        for band in section_bands
    ):
        return "axisymmetric"
    if any(
        isinstance(_dict_get(band, "width"), (int, float)) or isinstance(_dict_get(band, "width_estimate"), (int, float))
        for band in section_bands
    ):
        return "prismatic"
    return "axisymmetric"


def _find_section_dimension(view: dict[str, Any] | None, label: str) -> float | None:
    if not view:
        return None
    semantic_aliases = {
        "total_height": {"total_height", "overall_height", "overall_height_bottom_to_hub_top", "overall_axial_length", "overall_length", "part_length"},
        "outer_diameter_flange": {"outer_diameter_flange", "outer_diameter", "overall_outer_diameter", "flange_outer_diameter", "top_flange_width", "overall_width"},
        "outer_diameter_body": {"outer_diameter_body", "hub_outer_diameter", "body_outer_diameter", "outer_diameter_hub", "hub_diameter", "hub_boss_outer_diameter", "vertical_wall_width", "wall_width"},
        "inner_diameter_upper": {"inner_diameter_upper", "upper_opening_diameter", "top_face_width", "hub_outer_diameter", "counterbore_diameter"},
        "inner_diameter_bore": {"inner_diameter_bore", "central_bore_diameter", "bore_diameter"},
        "recess_seat_diameter": {"recess_seat_diameter", "recess_outer_diameter", "annular_recess_outer_boundary_and_step_inner_boundary", "counterbore_diameter", "hub_step_diameter"},
        "lower_flange_height": {"lower_flange_height", "flange_thickness", "lower_section_height", "axial_band_width_1", "base_flange_lower_height", "base_height"},
        "middle_body_height": {"middle_body_height", "middle_band_height", "axial_band_width_2"},
        "upper_flange_height": {"upper_flange_height", "hub_height", "raised_hub_height", "axial_band_width_3", "top_flange_thickness", "top_flange_depth"},
        "bolt_circle_diameter": {"bolt_circle_diameter", "pattern_pitch_circle_diameter", "pitch_circle_diameter", "hole_pattern_pcd"},
    }
    candidates = semantic_aliases.get(label, {label})
    for item in view.get("dimensions", []):
        if not isinstance(item, dict):
            continue
        item_keys = {
            str(item.get("label", "")),
            str(item.get("dim_id", "")),
            str(item.get("semantic", "")),
        }
        lowered_item_keys = {value.lower() for value in item_keys if value}
        if any(candidate.lower() in lowered_item_keys for candidate in candidates):
            value = item.get("value")
            return float(value) if isinstance(value, (int, float)) else None
    return None


def _find_section_dimension_any(view: dict[str, Any] | None, *labels: str) -> float | None:
    for label in labels:
        value = _find_section_dimension(view, label)
        if value is not None:
            return value
    return None


def _find_dimension_by_label(view: dict[str, Any] | None, *labels: str) -> float | None:
    if not view:
        return None
    for label in labels:
        value = _find_section_dimension(view, label)
        if value is not None:
            return value
    return None


def _find_top_dimension(view: dict[str, Any] | None, target: str) -> float | None:
    if not view:
        return None
    for item in view.get("dimensions", []):
        if not isinstance(item, dict):
            continue
        comparison_values = {
            str(item.get("target", "")),
            str(item.get("applies_to", "")),
            str(item.get("reference", "")),
            str(item.get("label", "")),
            str(item.get("dim_id", "")),
            str(item.get("semantic", "")),
        }
        if target in comparison_values:
            value = item.get("value")
            return float(value) if isinstance(value, (int, float)) else None
    return None


def _find_top_dimension_any(view: dict[str, Any] | None, *targets: str) -> float | None:
    for target in targets:
        value = _find_top_dimension(view, target)
        if value is not None:
            return value
    return None


def _find_contour(view: dict[str, Any] | None, *, order: int | None = None, role: str | None = None) -> dict[str, Any] | None:
    if not view:
        return None
    for contour in view.get("contour_stack", []):
        if order is not None and contour.get("order") != order:
            continue
        if role is not None and contour.get("role") != role:
            continue
        return contour
    return None


def _view_contains_linear_measure(view: dict[str, Any] | None, target: float | int | None, tolerance: float = 1e-6) -> bool:
    if not view or not isinstance(target, (int, float)):
        return False

    expected = float(target)
    candidate_keys = ("width", "height", "length", "depth", "thickness", "outer_width", "outer_height")

    def _matches(value: Any) -> bool:
        return isinstance(value, (int, float)) and math.isclose(float(value), expected, rel_tol=0.0, abs_tol=tolerance)

    for contour in view.get("contour_stack", []):
        if not isinstance(contour, dict):
            continue
        if any(_matches(contour.get(key)) for key in candidate_keys):
            return True

    for entity in view.get("entities", []):
        if not isinstance(entity, dict):
            continue
        if any(_matches(entity.get(key)) for key in candidate_keys):
            return True
        dimensions = _as_dict(entity.get("dimensions")) or {}
        if any(_matches(dimensions.get(key)) for key in candidate_keys):
            return True

    for item in view.get("dimensions", []):
        if not isinstance(item, dict):
            continue
        if _matches(item.get("value")):
            return True

    return False


def _section_max_outer_span(view: dict[str, Any] | None) -> float | None:
    if not view:
        return None

    spans: list[float] = []
    for band in view.get("axial_bands", []):
        if not isinstance(band, dict):
            continue
        span = _first_numeric(
            band.get("outer_diameter"),
            band.get("width"),
            band.get("width_estimate"),
            band.get("outer_width"),
            band.get("outer_height"),
        )
        if span is not None:
            spans.append(float(span))
    return max(spans) if spans else None


def _view_contains_diameter(view: dict[str, Any] | None, diameter: float | int | None, tolerance: float = 1e-6) -> bool:
    if not view or not isinstance(diameter, (int, float)):
        return False
    target = float(diameter)
    for contour in view.get("contour_stack", []):
        value = contour.get("diameter") if isinstance(contour, dict) else None
        if isinstance(value, (int, float)) and math.isclose(float(value), target, rel_tol=0.0, abs_tol=tolerance):
            return True
    for entity in view.get("entities", []):
        if not isinstance(entity, dict):
            continue
        for key in ("diameter", "outer_diameter", "inner_diameter", "bolt_circle_diameter"):
            value = entity.get(key)
            if isinstance(value, (int, float)) and math.isclose(float(value), target, rel_tol=0.0, abs_tol=tolerance):
                return True
    for item in view.get("dimensions", []):
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if isinstance(value, (int, float)) and math.isclose(float(value), target, rel_tol=0.0, abs_tol=tolerance):
            return True
    return False


def _find_hole_pattern(view: dict[str, Any] | None) -> dict[str, Any] | None:
    candidates = [
        _find_entity(view, "bolt_hole_pattern"),
        _find_entity(view, "HP1"),
        _find_entity(view, "hole_pattern_1"),
        _find_entity_by_type(view, "hole_pattern"),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    return None


def _find_section_hole_pattern(view: dict[str, Any] | None) -> dict[str, Any] | None:
    candidates = [
        _find_entity(view, "bolt_holes"),
        _find_entity(view, "bolt_hole_pattern"),
        _find_entity_by_type(view, "hole_pattern"),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    return None


def _find_global_constraint(payload: dict[str, Any], constraint_name: str) -> dict[str, Any] | None:
    for item in payload.get("global_constraints", []):
        if isinstance(item, dict) and item.get("constraint") == constraint_name:
            return item
    return None


def _hole_pattern_count(entity: dict[str, Any] | None) -> float | None:
    return _first_numeric(
        _dict_get(entity, "count"),
        _dict_get(entity, "hole_count"),
        _dict_get(entity, "quantity"),
        _dict_get(_dict_get(entity, "pattern"), "count"),
    )


def _hole_pattern_pcd(entity: dict[str, Any] | None) -> float | None:
    return _first_numeric(
        _dict_get(entity, "bolt_circle_diameter"),
        _dict_get(entity, "pitch_circle_diameter"),
        _dict_get(entity, "PCD"),
        _dict_get(entity, "pcd"),
        _dict_get(_dict_get(entity, "repetition_rule"), "pitch_circle_diameter"),
        _dict_get(_dict_get(entity, "pattern"), "pitch_circle_diameter_mm"),
        _dict_get(_dict_get(entity, "feature_placement"), "diameter"),
    )


def _uncertainty_mentions(payload: dict[str, Any], *keywords: str) -> bool:
    lowered_keywords = [keyword.lower() for keyword in keywords]
    collections: list[Any] = [payload.get("uncertainties", [])]
    for view in payload.get("views", []):
        if isinstance(view, dict):
            collections.append(view.get("uncertainties", []))
    for collection in collections:
        for item in collection:
            if isinstance(item, dict):
                text = " ".join(str(value) for value in item.values())
            else:
                text = str(item)
            lowered = text.lower()
            if any(keyword in lowered for keyword in lowered_keywords):
                return True
    return False


def _coerce_hole_start_face(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    mapping = {
        "top": "top",
        "top_face": "top",
        "bottom": "bottom",
        "bottom_face": "bottom",
        "upper_step": "upper_step",
        "upper_step_face": "upper_step",
        "recess_floor": "upper_step",
        "internal_floor": "upper_step",
        "lower_step": "lower_step",
        "lower_step_face": "lower_step",
    }
    return mapping.get(value)


def normalize_analysis_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(payload)
    top_view = _find_view(normalized, "top")
    section_view = _find_view(normalized, "section")
    top_hole_pattern = _as_dict(_find_hole_pattern(top_view))
    section_hole_pattern = _as_dict(_find_section_hole_pattern(section_view))
    recessed_hole_seat = _as_dict(_find_entity(section_view, "recessed_hole_seat") or _find_entity(section_view, "upper_recess"))
    hole_count_constraint = _find_global_constraint(normalized, "hole_pattern_count")
    pcd_constraint = _find_global_constraint(normalized, "bolt_circle_diameter")
    top_upper_opening_diameter = _first_numeric(
        _find_dimension_by_label(top_view, "inner_diameter_upper", "upper_opening_diameter"),
        _dict_get(_find_entity(top_view, "upper_opening"), "diameter"),
        _dict_get(_find_contour(top_view, role="visible_opening"), "diameter"),
    )
    fillet_radius = _first_numeric(
        _dict_get(_find_entity(section_view, "fillet_inner") or _find_entity(section_view, "fillet_inner_step"), "radius"),
        _dict_get(_find_entity(top_view, "fillet_inner"), "radius"),
    )
    central_bore_diameter = _first_numeric(
        _dict_get(_find_entity(section_view, "central_bore") or _find_entity_by_type(section_view, "through_hole", "through_bore"), "diameter"),
        _dict_get(_find_entity(top_view, "central_bore"), "diameter"),
        _find_dimension_by_label(top_view, "inner_diameter_bore"),
    )
    recessed_floor_z = _first_numeric(
        _dict_get(_find_entity(section_view, "upper_recess"), "floor_z"),
        _dict_get(_find_entity(section_view, "recessed_hole_seat"), "z_level"),
    )

    if top_hole_pattern is not None:
        if top_hole_pattern.get("count") is None:
            inferred_count = _first_numeric(
                _dict_get(top_hole_pattern, "hole_count"),
                _dict_get(hole_count_constraint, "value"),
            )
            if inferred_count is not None:
                top_hole_pattern["count"] = int(inferred_count)
        if top_hole_pattern.get("bolt_circle_diameter") is None:
            inferred_pcd = _first_numeric(
                _hole_pattern_pcd(top_hole_pattern),
                _dict_get(pcd_constraint, "value"),
            )
            if inferred_pcd is not None:
                top_hole_pattern["bolt_circle_diameter"] = inferred_pcd

    if section_view is not None and section_hole_pattern is None:
        inferred_count = _first_numeric(
            _hole_pattern_count(top_hole_pattern),
            _dict_get(hole_count_constraint, "value"),
        )
        inferred_pcd = _first_numeric(
            _hole_pattern_pcd(top_hole_pattern),
            _dict_get(pcd_constraint, "value"),
        )
        inferred_start_face = None
        if recessed_hole_seat is not None:
            inferred_start_face = "upper_step"
        inferred_start_face = inferred_start_face or _coerce_hole_start_face(_dict_get(top_hole_pattern, "visible_on_face"))
        if inferred_count is not None or inferred_pcd is not None or inferred_start_face is not None:
            section_view.setdefault("entities", []).append(
                {
                    "id": "bolt_holes",
                    "type": "hole_pattern",
                    "count": int(inferred_count) if inferred_count is not None else None,
                    "bolt_circle_diameter": inferred_pcd,
                    "start_face": inferred_start_face or "unknown",
                    "axial_layer": "upper_flange" if inferred_start_face == "upper_step" else "unknown",
                    "evidence": "Auto-normalized from top-view hole pattern and section seat geometry.",
                }
            )
            section_hole_pattern = _as_dict(_find_section_hole_pattern(section_view))

    if top_hole_pattern is not None and section_hole_pattern is not None:
        if section_hole_pattern.get("count") is None:
            inferred_count = _first_numeric(
                _hole_pattern_count(section_hole_pattern),
                _hole_pattern_count(top_hole_pattern),
                _dict_get(hole_count_constraint, "value"),
            )
            if inferred_count is not None:
                section_hole_pattern["count"] = int(inferred_count)
        if section_hole_pattern.get("bolt_circle_diameter") is None:
            inferred_pcd = _first_numeric(
                _hole_pattern_pcd(section_hole_pattern),
                _hole_pattern_pcd(top_hole_pattern),
                _dict_get(pcd_constraint, "value"),
            )
            if inferred_pcd is not None:
                section_hole_pattern["bolt_circle_diameter"] = inferred_pcd
        if not section_hole_pattern.get("start_face"):
            inferred_start_face = "upper_step" if recessed_hole_seat is not None else _coerce_hole_start_face(_dict_get(top_hole_pattern, "visible_on_face"))
            if inferred_start_face is not None:
                section_hole_pattern["start_face"] = inferred_start_face

    hole_ring_on_lower_face = top_hole_pattern is not None and _dict_get(top_hole_pattern, "visible_on_face") in {"recess_floor", "internal_floor", "lower_step_face"}
    if hole_ring_on_lower_face:
        inferred_pcd = _first_numeric(
            _hole_pattern_pcd(top_hole_pattern),
            _dict_get(pcd_constraint, "value"),
        )
        derived_seat_outer = None
        if isinstance(top_upper_opening_diameter, (int, float)) and isinstance(fillet_radius, (int, float)):
            candidate = float(top_upper_opening_diameter) - 2.0 * float(fillet_radius)
            if inferred_pcd is None or candidate > float(inferred_pcd):
                derived_seat_outer = candidate
        if derived_seat_outer is not None and (recessed_hole_seat is None or _first_numeric(_dict_get(recessed_hole_seat, "outer_diameter"), _dict_get(recessed_hole_seat, "inner_diameter")) in (None, inferred_pcd) or (_first_numeric(_dict_get(recessed_hole_seat, "outer_diameter"), _dict_get(recessed_hole_seat, "inner_diameter")) is not None and inferred_pcd is not None and _first_numeric(_dict_get(recessed_hole_seat, "outer_diameter"), _dict_get(recessed_hole_seat, "inner_diameter")) <= inferred_pcd)):
            seat_entity = {
                "id": "recessed_hole_seat",
                "type": "annular_floor",
                "outer_diameter": derived_seat_outer,
                "inner_diameter": central_bore_diameter,
                "z_level": recessed_floor_z,
                "evidence": "Auto-normalized from upper opening diameter, inner fillet radius, and lower-face hole ring geometry.",
            }
            if section_view is not None:
                entities = section_view.setdefault("entities", [])
                existing_index = next((index for index, entity in enumerate(entities) if isinstance(entity, dict) and entity.get("id") == "recessed_hole_seat"), None)
                if existing_index is None:
                    entities.append(seat_entity)
                else:
                    entities[existing_index] = seat_entity
                recessed_hole_seat = seat_entity

    return normalized


def _has_entity_type(view: dict[str, Any] | None, entity_type: str) -> bool:
    if not view:
        return False
    return any(isinstance(entity, dict) and entity.get("type") == entity_type for entity in view.get("entities", []))


def build_contract(payload: dict[str, Any]) -> dict[str, Any]:
    payload = normalize_analysis_payload(payload)
    top_view = _find_view(payload, "top")
    section_view = _find_view(payload, "section")
    geometry_family = _infer_geometry_family(payload, top_view, section_view)
    bolt_holes = _as_dict(_find_section_hole_pattern(section_view))
    top_hole_pattern = _as_dict(_find_hole_pattern(top_view))
    central_bore_top = _as_dict(_find_entity(top_view, "central_bore") or _find_entity_by_type(top_view, "bore", "through_hole"))
    central_bore_section = _as_dict(_find_entity(section_view, "central_bore") or _find_entity_by_type(section_view, "through_bore", "through_hole"))
    upper_opening = _as_dict(_find_entity(top_view, "upper_opening"))
    recessed_hole_seat = _as_dict(_find_entity(section_view, "recessed_hole_seat") or _find_entity(section_view, "upper_recess"))
    fillet_inner = _as_dict(_find_entity(section_view, "fillet_inner") or _find_entity(section_view, "fillet_inner_step"))
    top_outer_contour = _find_contour(top_view, order=1, role="outer_silhouette")
    top_pattern_reference = _find_contour(top_view, role="pattern_reference")
    top_visible_openings = [entity for entity in _find_entities_by_type(top_view, "bore") if entity.get("visible_on_face") in {"recess_floor", "internal_floor"}]
    top_recess_boundary = _find_contour(top_view, role="recess_boundary")
    section_bands = section_view.get("axial_bands", []) if section_view else []
    numeric_band_starts = [float(band.get("axial_start")) for band in section_bands if _numeric_value(band.get("axial_start")) is not None]
    numeric_band_ends = [float(band.get("axial_end")) for band in section_bands if _numeric_value(band.get("axial_end")) is not None]
    derived_total_height = None
    if numeric_band_starts and numeric_band_ends:
        derived_total_height = max(numeric_band_ends) - min(numeric_band_starts)
    total_height = _first_numeric(
        _find_section_dimension_any(section_view, "total_height"),
        derived_total_height,
    )

    top_hole_count = _hole_pattern_count(top_hole_pattern)
    top_hole_pcd = _first_numeric(
        _hole_pattern_pcd(top_hole_pattern),
        top_pattern_reference.get("diameter") if top_pattern_reference else None,
        _find_dimension_by_label(top_view, "bolt_circle_diameter"),
    )
    section_hole_count = _hole_pattern_count(bolt_holes)
    section_hole_pcd = _hole_pattern_pcd(bolt_holes)
    section_hole_start_face = (
        _dict_get(bolt_holes, "axial_start_face")
        or _dict_get(bolt_holes, "start_face")
        or _dict_get(_dict_get(bolt_holes, "feature_placement", {}), "start_face")
    )

    upper_band = next((band for band in section_bands if band.get("band_role") in {"top_rim", "upper_opening", "upper_flange"}), None)
    middle_band = next((band for band in section_bands if band.get("band_role") in {"solid_wall", "middle_bore", "middle_body"}), None)
    lower_band = next((band for band in section_bands if band.get("band_role") in {"lower_bore", "lower_flange"}), None)
    numeric_bands = [
        band
        for band in section_bands
        if _numeric_value(band.get("axial_start")) is not None and _numeric_value(band.get("axial_end")) is not None
    ]
    if upper_band is None and isinstance(total_height, (int, float)):
        upper_candidates = [
            band
            for band in section_bands
            if _numeric_value(band.get("axial_end")) is not None
            and math.isclose(float(band.get("axial_end")), float(total_height), rel_tol=0.0, abs_tol=1e-6)
            and _numeric_value(band.get("axial_start")) is not None
        ]
        if upper_candidates:
            upper_band = max(upper_candidates, key=lambda band: float(band.get("axial_start")))
    if lower_band is None and numeric_bands:
        lower_band = max(numeric_bands, key=lambda band: float(band.get("axial_end")))

    def _band_height(band: dict[str, Any] | None) -> float | None:
        if not band:
            return None
        if _numeric_value(band.get("axial_start")) is None or _numeric_value(band.get("axial_end")) is None:
            return None
        return float(band.get("axial_end")) - float(band.get("axial_start"))

    upper_band_height = _band_height(upper_band)
    middle_band_height = _band_height(middle_band)
    lower_band_height = _band_height(lower_band)
    if lower_band_height is None and isinstance(total_height, (int, float)) and isinstance(upper_band_height, (int, float)) and isinstance(middle_band_height, (int, float)):
        residual_lower_height = float(total_height) - float(upper_band_height) - float(middle_band_height)
        if residual_lower_height > 0:
            lower_band_height = residual_lower_height

    top_outer_size = _first_numeric(
        top_outer_contour.get("diameter") if top_outer_contour else None,
        top_outer_contour.get("width") if top_outer_contour else None,
        _find_dimension_by_label(top_view, "outer_diameter_flange", "overall_width", "top_flange_width"),
    )
    top_outer_width = _first_numeric(
        top_outer_contour.get("width") if top_outer_contour else None,
        _find_dimension_by_label(top_view, "overall_width", "footprint_width", "overall_length", "base_length"),
    )
    top_outer_height = _first_numeric(
        top_outer_contour.get("height") if top_outer_contour else None,
        _find_dimension_by_label(top_view, "overall_height", "footprint_height", "overall_depth", "base_depth"),
    )
    section_max_span = _section_max_outer_span(section_view)
    body_outer_size = _first_numeric(
        _find_section_dimension_any(section_view, "outer_diameter_body", "step_OD_1", "vertical_wall_width", "wall_width"),
        middle_band.get("outer_diameter") if middle_band else None,
        middle_band.get("width") if middle_band else None,
        middle_band.get("width_estimate") if middle_band else None,
        top_recess_boundary.get("diameter") if top_recess_boundary else None,
    )

    return {
        "geometry_family": geometry_family,
        "top_view_present": top_view is not None,
        "section_view_present": section_view is not None,
        "top_outer_width": top_outer_width,
        "top_outer_height": top_outer_height,
        "section_max_span": section_max_span,
        "outer_diameter_flange": _first_numeric(
            _find_section_dimension_any(section_view, "outer_diameter_flange", "flange_OD"),
            upper_band.get("outer_diameter") if upper_band else None,
            top_outer_size,
            _find_top_dimension_any(top_view, "outer_circle", "outer_silhouette"),
        ),
        "outer_diameter_body": body_outer_size,
        "inner_diameter_upper": _first_numeric(
            _find_section_dimension_any(section_view, "inner_diameter_upper", "step_OD_2"),
            upper_band.get("inner_diameter") if upper_band else None,
            upper_opening.get("diameter") if upper_opening else None,
            _find_contour(top_view, role="visible_opening").get("diameter") if _find_contour(top_view, role="visible_opening") else None,
        ),
        "inner_diameter_bore": _first_numeric(
            _find_section_dimension_any(section_view, "inner_diameter_bore", "bore_ID"),
            central_bore_section.get("diameter") if central_bore_section else None,
            central_bore_top.get("inner_diameter") if central_bore_top else None,
            central_bore_top.get("diameter") if central_bore_top else None,
        ),
        "recess_seat_diameter": _first_numeric(
            recessed_hole_seat.get("outer_diameter") if recessed_hole_seat else None,
            _find_section_dimension_any(section_view, "recess_seat_diameter"),
            recessed_hole_seat.get("inner_diameter") if recessed_hole_seat else None,
            top_recess_boundary.get("diameter") if top_recess_boundary else None,
        ),
        "total_height": total_height,
        "lower_flange_height": _first_numeric(
            _find_section_dimension_any(section_view, "lower_flange_height", "lower_section_height"),
            lower_band_height,
        ),
        "middle_body_height": _first_numeric(
            _find_section_dimension_any(section_view, "middle_body_height", "middle_band_height"),
            middle_band_height,
        ),
        "upper_flange_height": _first_numeric(
            _find_section_dimension_any(section_view, "upper_flange_height"),
            upper_band_height,
        ),
        "upper_opening_diameter": _first_numeric(
            _find_dimension_by_label(top_view, "inner_diameter_upper", "upper_opening_diameter"),
            _dict_get(upper_opening, "diameter"),
            _dict_get(central_bore_top, "outer_diameter"),
            _dict_get(top_visible_openings[0] if top_visible_openings else None, "outer_diameter"),
            _dict_get(_find_contour(top_view, order=4), "diameter"),
        ),
        "recess_floor_z": _first_numeric(
            _dict_get(recessed_hole_seat, "z_level"),
            _dict_get(_find_entity(section_view, "upper_recess"), "floor_z"),
            middle_band.get("axial_end") if middle_band else None,
        ),
        "lower_bore_step_z": _first_numeric(
            lower_band.get("axial_end") if lower_band else None,
            _dict_get(_find_entity(section_view, "lower_bore"), "depth"),
        ),
        "hole_count": _first_numeric(section_hole_count, top_hole_count),
        "bolt_circle_diameter": _first_numeric(section_hole_pcd, top_hole_pcd),
        "hole_start_face": section_hole_start_face or _dict_get(top_hole_pattern, "visible_on_face"),
        "hole_layer": _dict_get(bolt_holes, "axial_layer") or _dict_get(_dict_get(top_hole_pattern, "feature_placement", {}), "target_layer"),
        "needs_bottom_outer_chamfer": _find_entity(section_view, "bottom_outer_chamfer") is not None,
        "needs_inner_fillet": fillet_inner is not None,
        "needs_recessed_hole_seat": recessed_hole_seat is not None,
    }


def validate_analysis_payload(payload: dict[str, Any]) -> list[str]:
    payload = normalize_analysis_payload(payload)
    issues: list[str] = []
    contract = build_contract(payload)
    top_view = _find_view(payload, "top")
    section_view = _find_view(payload, "section")
    top_hole_pattern = _find_hole_pattern(top_view)
    section_hole_pattern = _find_section_hole_pattern(section_view)
    geometry_family = contract.get("geometry_family", "axisymmetric")
    summary_text = " ".join(str(value) for value in (_as_dict(payload.get("drawing_summary")) or {}).values()).lower()
    top_view_text = " ".join(
        [
            str(top_view.get("summary", "")) if top_view else "",
            *(str(note) for note in (top_view.get("notes", []) if top_view else [])),
        ]
    ).lower()
    hole_ring_on_lower_face = (
        (top_hole_pattern is not None and top_hole_pattern.get("visible_on_face") in {"recess_floor", "internal_floor", "lower_step_face"})
        or contract["hole_start_face"] in {"upper_step", "lower_step"}
    )

    if not contract["top_view_present"]:
        issues.append("缺少顶视图 JSON。")
    if not contract["section_view_present"]:
        issues.append("缺少剖视图 JSON。")

    if geometry_family == "prismatic":
        section_max_span = contract.get("section_max_span")
        top_outer_width = contract.get("top_outer_width")
        top_outer_height = contract.get("top_outer_height")
        top_has_bore_or_pattern = top_hole_pattern is not None or _find_entity(top_view, "central_bore") is not None
        top_mentions_base_footprint = any(
            keyword in f"{summary_text} {top_view_text}"
            for keyword in ("base", "foot", "pocket", "bracket", "support", "pedestal", "hidden")
        )
        has_hidden_rectangular_contour = any(
            isinstance(contour, dict)
            and str(contour.get("shape", "")).lower() in {"rectangular_outline_dashed", "rectangle", "rectangular_outline"}
            and contour.get("role") in {"hidden_only", "outer_silhouette"}
            for contour in (top_view.get("contour_stack", []) if top_view else [])
        )

        if (
            isinstance(section_max_span, (int, float))
            and not _view_contains_linear_measure(top_view, section_max_span)
            and (top_mentions_base_footprint or has_hidden_rectangular_contour)
        ):
            issues.append(
                "支架/棱柱件的 top_view 未显式记录底座平面主跨度；剖视已给出更大的外形跨度，疑似把立板正视图误标为 top_view。"
            )

        if (
            isinstance(section_max_span, (int, float))
            and isinstance(top_outer_width, (int, float))
            and isinstance(top_outer_height, (int, float))
            and isinstance(contract.get("total_height"), (int, float))
            and math.isclose(float(top_outer_height), float(contract["total_height"]), rel_tol=0.0, abs_tol=1e-6)
            and float(section_max_span) > float(top_outer_width)
            and top_has_bore_or_pattern
        ):
            issues.append(
                "prismatic 零件当前的 top_view 更像立板正视图：它同时承载了整件高度和圆孔真形，但没有表达更大的底座平面跨度。"
            )

    required_keys = [
        "outer_diameter_flange",
        "outer_diameter_body",
        "inner_diameter_upper",
        "inner_diameter_bore",
        "total_height",
        "lower_flange_height",
        "middle_body_height",
        "upper_flange_height",
        "hole_count",
        "bolt_circle_diameter",
    ]
    if geometry_family == "axisymmetric" or hole_ring_on_lower_face or contract["needs_recessed_hole_seat"]:
        required_keys.append("recess_seat_diameter")

    for key in required_keys:
        if key == "bolt_circle_diameter" and contract.get(key) in (None, "unknown"):
            if _uncertainty_mentions(payload, "bolt_circle_diameter", "pcd", "pitch circle"):
                continue
        if contract.get(key) in (None, "unknown"):
            issues.append(f"契约字段缺失: {key}。")

    top_outer = _first_numeric(_find_top_dimension_any(top_view, "outer_circle", "outer_silhouette"), (_find_contour(top_view, order=1, role="outer_silhouette") or {}).get("diameter"))
    section_outer = _find_section_dimension_any(section_view, "outer_diameter_flange", "flange_OD")
    if top_outer and section_outer and not math.isclose(top_outer, section_outer, rel_tol=0.0, abs_tol=1e-6):
        issues.append(f"顶视外径与剖视外径不一致: {top_outer} vs {section_outer}。")

    top_upper_opening = contract["upper_opening_diameter"]
    section_upper_opening = _first_numeric(
        contract["inner_diameter_upper"],
        (_find_entity(section_view, "upper_counterbore") or {}).get("diameter"),
        (_find_entity(section_view, "upper_recess") or {}).get("inner_diameter"),
    )
    has_explicit_upper_opening_evidence = (
        _find_entity(top_view, "upper_opening") is not None
        or _find_dimension_by_label(top_view, "inner_diameter_upper", "upper_opening_diameter") is not None
        or _find_entity(section_view, "upper_recess") is not None
        or _find_entity(section_view, "recessed_hole_seat") is not None
    )
    if has_explicit_upper_opening_evidence and isinstance(top_upper_opening, (int, float)) and isinstance(section_upper_opening, (int, float)):
        if not math.isclose(float(top_upper_opening), float(section_upper_opening), rel_tol=0.0, abs_tol=1e-6):
            if not (
                _find_entity(section_view, "recessed_hole_seat") is not None
                and _view_contains_diameter(top_view, top_upper_opening)
                and _view_contains_diameter(top_view, section_upper_opening)
            ):
                issues.append("顶视可见上开口直径与剖视上台阶孔直径不一致。")

    top_bore = contract["inner_diameter_bore"]
    section_bore = _first_numeric((_find_entity(section_view, "central_bore") or {}).get("diameter"), (_find_entity_by_type(section_view, "through_bore", "through_hole") or {}).get("diameter"))
    if isinstance(top_bore, (int, float)) and isinstance(section_bore, (int, float)):
        if not math.isclose(float(top_bore), float(section_bore), rel_tol=0.0, abs_tol=1e-6):
            issues.append("顶视深层通孔直径与剖视中心孔直径不一致。")

    if top_hole_pattern is None:
        issues.append("顶视图缺少螺栓孔阵列实体。")
    if section_hole_pattern is None:
        issues.append("剖视图缺少螺栓孔阵列实体。")

    if top_hole_pattern and section_hole_pattern:
        top_count = _hole_pattern_count(_as_dict(top_hole_pattern))
        section_count = _hole_pattern_count(_as_dict(section_hole_pattern))
        if top_count is not None and section_count is not None and top_count != section_count:
            issues.append("顶视与剖视的孔数量不一致。")
        top_pcd = _hole_pattern_pcd(_as_dict(top_hole_pattern))
        section_pcd = _hole_pattern_pcd(_as_dict(section_hole_pattern))
        if isinstance(top_pcd, (int, float)) and isinstance(section_pcd, (int, float)):
            if not math.isclose(float(top_pcd), float(section_pcd), rel_tol=0.0, abs_tol=1e-6):
                issues.append("顶视与剖视的孔阵列直径不一致。")

        top_visible_face = top_hole_pattern.get("visible_on_face")
        section_start_face = section_hole_pattern.get("axial_start_face") or section_hole_pattern.get("start_face")
        if top_visible_face in {"recess_floor", "internal_floor", "lower_step_face"} and section_start_face == "top":
            issues.append("顶视已说明孔图元来自下层可见面，但剖视仍把孔起始面写成 top。")
        if section_start_face in {"upper_step", "lower_step"} and top_visible_face == "top_face":
            issues.append("剖视已说明孔从凹台阶面起孔，但顶视仍把孔可见面写成 top_face。")

    if hole_ring_on_lower_face and not contract["needs_recessed_hole_seat"]:
        issues.append("孔阵列位于下层可见面或凹台阶起孔，但剖视未显式提供 recessed_hole_seat 实体。")

    if (
        isinstance(contract["bolt_circle_diameter"], (int, float))
        and isinstance(contract["recess_seat_diameter"], (int, float))
        and math.isclose(float(contract["bolt_circle_diameter"]), float(contract["recess_seat_diameter"]), rel_tol=0.0, abs_tol=1e-6)
    ):
        issues.append("孔阵列 PCD 被误写成凹台阶座面边界直径。")

    if (
        hole_ring_on_lower_face
        and isinstance(contract["bolt_circle_diameter"], (int, float))
        and isinstance(contract["recess_seat_diameter"], (int, float))
        and float(contract["bolt_circle_diameter"]) >= float(contract["recess_seat_diameter"])
    ):
        issues.append("孔阵列 PCD 必须落在凹台阶座面边界之内，不能大于或等于座面外边界直径。")

    if (
        hole_ring_on_lower_face
        and isinstance(contract["bolt_circle_diameter"], (int, float))
        and isinstance(contract["inner_diameter_bore"], (int, float))
        and float(contract["bolt_circle_diameter"]) <= float(contract["inner_diameter_bore"])
    ):
        issues.append("孔阵列 PCD 必须位于中心孔外侧，不能小于或等于下层可见中心孔直径。")

    if (
        hole_ring_on_lower_face
        and isinstance(contract["bolt_circle_diameter"], (int, float))
        and isinstance(contract["outer_diameter_body"], (int, float))
        and float(contract["bolt_circle_diameter"]) >= float(contract["outer_diameter_body"])
        and not (
            isinstance(contract["recess_seat_diameter"], (int, float))
            and float(contract["recess_seat_diameter"]) > float(contract["bolt_circle_diameter"])
        )
    ):
        issues.append("若孔阵列位于内部凹台阶座面，支撑该座面的外边界直径必须大于 PCD；当前 outer_diameter_body 很可能被误写成内部直径。")

    if (
        contract["needs_recessed_hole_seat"]
        and isinstance(contract["upper_opening_diameter"], (int, float))
        and isinstance(contract["recess_seat_diameter"], (int, float))
        and float(contract["upper_opening_diameter"]) <= float(contract["recess_seat_diameter"])
    ):
        issues.append("存在凹台阶座面时，上开口直径应大于座面外边界直径。")

    if (
        contract["needs_recessed_hole_seat"]
        and isinstance(contract["recess_seat_diameter"], (int, float))
        and isinstance(contract["inner_diameter_bore"], (int, float))
        and float(contract["recess_seat_diameter"]) <= float(contract["inner_diameter_bore"])
    ):
        issues.append("凹台阶座面外边界直径应大于下层可见中心孔直径。")

    if any("does not intersect" in note.lower() or "not intersect" in note.lower() for note in payload.get("section_interpretation", {}).get("notes", [])):
        if section_hole_pattern and "slot" in (section_hole_pattern.get("notes") or "").lower():
            issues.append("剖视说明切平面未穿过孔轴，但剖视实体仍把孔写成直接可见槽。")

    if contract["hole_start_face"] in {"upper_step", "lower_step"} and not contract["needs_recessed_hole_seat"]:
        issues.append("剖视已声明孔从凹台阶面开孔，但缺少 recessed_hole_seat 实体。")

    if contract["needs_bottom_outer_chamfer"] and "bottom_outer_edge_has_chamfer" not in payload.get("global_constraints", []):
        issues.append("剖视包含底部倒角，但 global_constraints 未声明。")

    if contract["bolt_circle_diameter"] and contract["upper_opening_diameter"]:
        if math.isclose(contract["bolt_circle_diameter"], contract["upper_opening_diameter"], rel_tol=0.0, abs_tol=1e-6):
            issues.append("孔阵列 PCD 与上部可见开口直径被写成同一个数值，需要确认是否混淆了开口直径和孔中心圆。")

    return issues


def format_analysis_report(payload: dict[str, Any]) -> str:
    issues = validate_analysis_payload(payload)
    contract = build_contract(payload)
    lines = ["# Analysis Alignment Report", ""]
    lines.append("## Contract")
    lines.append(json.dumps(contract, ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("## Issues")
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("- OK")
    lines.append("")
    lines.append("## Required visual checks")
    lines.append("- 顶视图是否只记录可见圆，不把深层隐藏孔误记成可见轮廓。")
    lines.append("- 顶视图里的可见圆是否区分了所属物理面，例如顶面边、凹台阶面边、以及透过上开口看到的下层面边。")
    lines.append("- 如果孔阵列从内部台阶面起孔，顶视 JSON 是否同时表达了‘从上方可见’和‘真实起孔面不在顶面’这两个事实。")
    lines.append("- 剖视图是否明确了孔口起始面是顶面、底面还是凹台阶面。")
    lines.append("- 剖视轮廓里可见的底部倒角、外轮廓退刀或台阶是否都单独建模。")
    return "\n".join(lines) + "\n"


def _collect_numeric_constants(code: str) -> set[float]:
    tree = ast.parse(code)
    values: set[float] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            values.add(float(node.value))
    return values


def _contains_number(code_numbers: set[float], expected: float | int | None) -> bool:
    if expected is None or not isinstance(expected, (int, float)):
        return False
    expected_value = float(expected)
    return any(math.isclose(value, expected_value, rel_tol=0.0, abs_tol=1e-6) for value in code_numbers)


def validate_generated_code(code: str, payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    contract = build_contract(payload)
    geometry_family = contract.get("geometry_family", "axisymmetric")
    code_numbers = _collect_numeric_constants(code)
    section_view = _find_view(payload, "section")
    section_fillet = _as_dict(_find_entity(section_view, "fillet_inner") or _find_entity(section_view, "fillet_inner_step"))
    has_profile_round = any(token in code for token in ("threePointArc(", "radiusArc(", "sagittaArc("))
    defined_tags = set(re.findall(r'\.tag\(\s*["\']([^"\']+)["\']\s*\)', code))
    referenced_tags = set(re.findall(r'workplaneFromTagged\(\s*["\']([^"\']+)["\']\s*\)', code))
    standalone_boolean_cut = re.search(
        r'cq\.Workplane\("[^"]+"(?:\s*,[^\)]*)?\)(?:(?!exporters\.export).)*\.workplane\([^\)]*\)(?:(?!exporters\.export).)*\.(?:circle|rect|slot2D|pushPoints)\([^\)]*\)(?:(?!exporters\.export).)*\.(cutBlind|cutThruAll)\(',
        code,
        re.DOTALL,
    )
    unsupported_loftcombine = re.search(r'\.loft\([^\)]*\bloftCombine\s*=', code)

    def has_number(expected: float | int | None) -> bool:
        return _contains_number(code_numbers, expected)

    derived_middle_height_ok = (
        contract.get("middle_body_height") is not None
        and has_number(contract.get("recess_floor_z"))
        and has_number(contract.get("lower_flange_height"))
    )
    derived_upper_height_ok = (
        contract.get("upper_flange_height") is not None
        and has_number(contract.get("total_height"))
        and has_number(contract.get("recess_floor_z"))
    )

    required_keys = [
        "outer_diameter_flange",
        "outer_diameter_body",
        "inner_diameter_upper",
        "inner_diameter_bore",
        "total_height",
        "lower_flange_height",
        "hole_count",
        "bolt_circle_diameter",
    ]
    if geometry_family == "axisymmetric" or contract["needs_recessed_hole_seat"] or contract["hole_start_face"] in {"upper_step", "lower_step"}:
        required_keys.append("recess_seat_diameter")

    for key in required_keys:
        if contract.get(key) is not None and not has_number(contract[key]):
            issues.append(f"代码缺少契约数值: {key}={contract[key]}。")

    if contract.get("middle_body_height") is not None and not (has_number(contract["middle_body_height"]) or derived_middle_height_ok):
        issues.append(f"代码缺少契约数值: middle_body_height={contract['middle_body_height']}。")

    if contract.get("upper_flange_height") is not None and not (has_number(contract["upper_flange_height"]) or derived_upper_height_ok):
        issues.append(f"代码缺少契约数值: upper_flange_height={contract['upper_flange_height']}。")

    if "exporters.export" not in code:
        issues.append("代码缺少 STEP 导出。")

    for tag_name in sorted(referenced_tags - defined_tags):
        issues.append(f"代码引用了未定义的 tagged workplane: {tag_name}。")

    if standalone_boolean_cut:
        issues.append("代码在全新 Workplane 上直接调用 cutBlind/cutThruAll，CadQuery 没有可切削的 solid。")

    if unsupported_loftcombine:
        issues.append("代码使用了当前 CadQuery 环境不支持的 loftCombine 参数。")

    if contract["needs_bottom_outer_chamfer"] and ".chamfer(" not in code:
        issues.append("JSON 要求底部倒角，但代码未调用 chamfer。")

    if contract["needs_inner_fillet"] and ".fillet(" not in code and not has_profile_round:
        issues.append("JSON 要求内圆角，但代码未调用 fillet。")

    if contract["needs_inner_fillet"] and "except Exception" in code and "pass  # Skip fillet" in code:
        issues.append("代码把必需的内圆角放进 try/except 后静默跳过，闭环执行风险过高。")

    if (
        contract["needs_inner_fillet"]
        and section_fillet is not None
        and section_fillet.get("location") in {"upper_internal_corner", "internal_step_corner"}
        and ".fillet(" in code
        and not has_profile_round
    ):
        issues.append("JSON 明确是剖面转角圆角，代码应优先用剖面圆弧直接建形，不要只依赖后置 edge fillet。")

    if contract["hole_start_face"] == "upper_step":
        upper_step_pattern = re.search(
            r"\.faces\(\">Z\[1\]\"\)(?:(?!exporters\.export).)*\.(?:polarArray|pushPoints)\((?:(?!exporters\.export).)*\.hole\(",
            code,
            re.DOTALL,
        )
        upper_step_face_pattern = re.search(
            r"\.faces\(\">Z\[-2\]\"\)(?:(?!exporters\.export).)*\.workplane\((?:(?!exporters\.export).)*\.(?:polarArray|pushPoints)\((?:(?!exporters\.export).)*(?:\.hole\(|\.circle\([^\n]*\)\s*\.cutBlind\()",
            code,
            re.DOTALL,
        )
        upper_step_workplane_pattern = re.search(
            r'Workplane\("XY",\s*origin=\(0,\s*0,\s*(?:recess_floor_z|upper_step_z|17(?:\.0+)?)\)\)(?:(?!exporters\.export).)*\.(?:polarArray|pushPoints)\((?:(?!exporters\.export).)*(?:\.hole\(|\.circle\([^\n]*\)\s*\.extrude\()',
            code,
            re.DOTALL,
        )
        upper_step_offset_workplane_pattern = re.search(
            r'Workplane\("XY"\)(?:(?!exporters\.export).)*\.workplane\(offset\s*=\s*(?:recess_floor_z|upper_step_z|17(?:\.0+)?)\)(?:(?!exporters\.export).)*\.circle\([^\n]*\)\s*\.extrude\(',
            code,
            re.DOTALL,
        )
        top_face_pattern = re.search(
            r"\.faces\(\">Z\"\)(?:(?!exporters\.export).)*\.(?:polarArray|pushPoints)\((?:(?!exporters\.export).)*(?:\.hole\(|\.circle\([^\n]*\)\s*\.cutBlind\()",
            code,
            re.DOTALL,
        )
        if not upper_step_pattern and not upper_step_face_pattern and not upper_step_workplane_pattern and not upper_step_offset_workplane_pattern:
            issues.append("JSON 要求孔从上侧凹台阶面开孔，但代码没有真正从 >Z[1] 台阶面启动孔阵列。")
        if top_face_pattern:
            issues.append("代码仍然从最上表面启动孔阵列，与 JSON 的 upper_step 起始面冲突。")

    if contract["hole_start_face"] == "bottom" and "faces(\"<Z\")" not in code:
        issues.append("JSON 要求孔从底面开孔，但代码未使用底面起始。")

    if contract["hole_layer"] == "upper_flange":
        upper_depth_pattern = re.search(
            r"depth\s*=\s*(upper_flange_height|UPPER_FLANGE_HEIGHT|upper_rim_height|UPPER_RIM_HEIGHT|8(?:\.0+)?)",
            code,
        )
        if not upper_depth_pattern:
            issues.append("JSON 要求孔作用于 upper_flange，但代码未把孔深绑定到 upper_flange_height。")

    if contract["hole_layer"] == "lower_flange":
        lower_depth_pattern = re.search(
            r"depth\s*=\s*(lower_flange_height|LOWER_FLANGE_HEIGHT|9(?:\.0+)?)",
            code,
        )
        if not lower_depth_pattern:
            issues.append("JSON 要求孔作用于 lower_flange，但代码未把孔深绑定到 lower_flange_height。")

    return issues


def format_code_report(code: str, payload: dict[str, Any]) -> str:
    issues = validate_generated_code(code, payload)
    contract = build_contract(payload)
    lines = ["# Code Alignment Report", ""]
    lines.append("## Contract")
    lines.append(json.dumps(contract, ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("## Issues")
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("- OK")
    return "\n".join(lines) + "\n"