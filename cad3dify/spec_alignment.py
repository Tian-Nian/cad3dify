import ast
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
        if entity.get("id") == entity_id:
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


def _find_section_dimension(view: dict[str, Any] | None, label: str) -> float | None:
    if not view:
        return None
    for item in view.get("dimensions", []):
        if item.get("label") == label:
            value = item.get("value")
            return float(value) if isinstance(value, (int, float)) else None
    return None


def _find_section_dimension_any(view: dict[str, Any] | None, *labels: str) -> float | None:
    for label in labels:
        value = _find_section_dimension(view, label)
        if value is not None:
            return value
    return None


def _find_top_dimension(view: dict[str, Any] | None, target: str) -> float | None:
    if not view:
        return None
    for item in view.get("dimensions", []):
        if item.get("target") == target or item.get("applies_to") == target or item.get("reference") == target:
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


def _has_entity_type(view: dict[str, Any] | None, entity_type: str) -> bool:
    if not view:
        return False
    return any(isinstance(entity, dict) and entity.get("type") == entity_type for entity in view.get("entities", []))


def build_contract(payload: dict[str, Any]) -> dict[str, Any]:
    top_view = _find_view(payload, "top")
    section_view = _find_view(payload, "section")
    bolt_holes = _as_dict(_find_section_hole_pattern(section_view))
    top_hole_pattern = _as_dict(_find_hole_pattern(top_view))
    central_bore_top = _as_dict(_find_entity(top_view, "central_bore") or _find_entity_by_type(top_view, "bore", "through_hole"))
    central_bore_section = _as_dict(_find_entity(section_view, "central_bore") or _find_entity_by_type(section_view, "through_bore", "through_hole"))
    upper_opening = _as_dict(_find_entity(top_view, "upper_opening"))
    recessed_hole_seat = _as_dict(_find_entity(section_view, "recessed_hole_seat") or _find_entity(section_view, "upper_recess"))
    fillet_inner = _as_dict(_find_entity(section_view, "fillet_inner") or _find_entity(section_view, "fillet_inner_step"))
    top_outer_contour = _find_contour(top_view, order=1, role="outer_silhouette")
    top_visible_openings = [entity for entity in _find_entities_by_type(top_view, "bore") if entity.get("visible_on_face") in {"recess_floor", "internal_floor"}]
    top_recess_boundary = _find_contour(top_view, role="recess_boundary")
    section_bands = section_view.get("axial_bands", []) if section_view else []

    top_hole_count = _first_numeric(_dict_get(top_hole_pattern, "count"), _dict_get(top_hole_pattern, "quantity"))
    top_hole_pcd = _first_numeric(
        _dict_get(top_hole_pattern, "bolt_circle_diameter"),
        _dict_get(top_hole_pattern, "PCD"),
        _dict_get(top_hole_pattern, "pcd"),
        _dict_get(_dict_get(top_hole_pattern, "feature_placement", {}), "diameter"),
    )
    section_hole_count = _first_numeric(_dict_get(bolt_holes, "count"), _dict_get(bolt_holes, "quantity"))
    section_hole_pcd = _first_numeric(
        _dict_get(bolt_holes, "bolt_circle_diameter"),
        _dict_get(bolt_holes, "PCD"),
        _dict_get(bolt_holes, "pcd"),
    )
    section_hole_start_face = (
        _dict_get(bolt_holes, "axial_start_face")
        or _dict_get(bolt_holes, "start_face")
        or _dict_get(_dict_get(bolt_holes, "feature_placement", {}), "start_face")
    )

    upper_band = next((band for band in section_bands if band.get("band_role") in {"top_rim", "upper_opening", "upper_flange"}), None)
    middle_band = next((band for band in section_bands if band.get("band_role") in {"solid_wall", "middle_bore", "middle_body"}), None)
    lower_band = next((band for band in section_bands if band.get("band_role") in {"lower_bore", "lower_flange"}), None)

    return {
        "top_view_present": top_view is not None,
        "section_view_present": section_view is not None,
        "outer_diameter_flange": _first_numeric(
            _find_section_dimension_any(section_view, "outer_diameter_flange", "flange_OD"),
            upper_band.get("outer_diameter") if upper_band else None,
            top_outer_contour.get("diameter") if top_outer_contour else None,
            _find_top_dimension_any(top_view, "outer_circle", "outer_silhouette"),
        ),
        "outer_diameter_body": _first_numeric(
            _find_section_dimension_any(section_view, "outer_diameter_body", "step_OD_1"),
            middle_band.get("outer_diameter") if middle_band else None,
            _find_contour(top_view, role="recess_boundary").get("diameter") if _find_contour(top_view, role="recess_boundary") else None,
        ),
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
            _find_section_dimension_any(section_view, "recess_seat_diameter"),
            recessed_hole_seat.get("inner_diameter") if recessed_hole_seat else None,
            top_recess_boundary.get("diameter") if top_recess_boundary else None,
        ),
        "total_height": _find_section_dimension_any(section_view, "total_height"),
        "lower_flange_height": _first_numeric(
            _find_section_dimension_any(section_view, "lower_flange_height", "lower_section_height"),
            (lower_band.get("axial_end") - lower_band.get("axial_start")) if lower_band and _numeric_value(lower_band.get("axial_end")) is not None and _numeric_value(lower_band.get("axial_start")) is not None else None,
        ),
        "middle_body_height": _first_numeric(
            _find_section_dimension_any(section_view, "middle_body_height", "middle_band_height"),
            (middle_band.get("axial_end") - middle_band.get("axial_start")) if middle_band and _numeric_value(middle_band.get("axial_end")) is not None and _numeric_value(middle_band.get("axial_start")) is not None else None,
        ),
        "upper_flange_height": _first_numeric(
            _find_section_dimension_any(section_view, "upper_flange_height"),
            (upper_band.get("axial_end") - upper_band.get("axial_start")) if upper_band and _numeric_value(upper_band.get("axial_end")) is not None and _numeric_value(upper_band.get("axial_start")) is not None else None,
        ),
        "upper_opening_diameter": _first_numeric(
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
    issues: list[str] = []
    contract = build_contract(payload)
    top_view = _find_view(payload, "top")
    section_view = _find_view(payload, "section")
    top_hole_pattern = _find_hole_pattern(top_view)
    section_hole_pattern = _find_section_hole_pattern(section_view)

    if not contract["top_view_present"]:
        issues.append("缺少顶视图 JSON。")
    if not contract["section_view_present"]:
        issues.append("缺少剖视图 JSON。")

    for key in (
        "outer_diameter_flange",
        "outer_diameter_body",
        "inner_diameter_upper",
        "inner_diameter_bore",
        "recess_seat_diameter",
        "total_height",
        "lower_flange_height",
        "middle_body_height",
        "upper_flange_height",
        "hole_count",
        "bolt_circle_diameter",
    ):
        if contract.get(key) in (None, "unknown"):
            issues.append(f"契约字段缺失: {key}。")

    top_outer = _first_numeric(_find_top_dimension_any(top_view, "outer_circle", "outer_silhouette"), (_find_contour(top_view, order=1, role="outer_silhouette") or {}).get("diameter"))
    section_outer = _find_section_dimension_any(section_view, "outer_diameter_flange", "flange_OD")
    if top_outer and section_outer and not math.isclose(top_outer, section_outer, rel_tol=0.0, abs_tol=1e-6):
        issues.append(f"顶视外径与剖视外径不一致: {top_outer} vs {section_outer}。")

    top_upper_opening = contract["upper_opening_diameter"]
    section_upper_opening = _first_numeric((_find_entity(section_view, "upper_counterbore") or {}).get("diameter"), (_find_entity(section_view, "upper_recess") or {}).get("outer_diameter"))
    if isinstance(top_upper_opening, (int, float)) and isinstance(section_upper_opening, (int, float)):
        if not math.isclose(float(top_upper_opening), float(section_upper_opening), rel_tol=0.0, abs_tol=1e-6):
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
        top_count = _first_numeric(top_hole_pattern.get("count"), top_hole_pattern.get("quantity"))
        section_count = _first_numeric(section_hole_pattern.get("count"), section_hole_pattern.get("quantity"))
        if top_count is not None and section_count is not None and top_count != section_count:
            issues.append("顶视与剖视的孔数量不一致。")
        top_pcd = _first_numeric(top_hole_pattern.get("bolt_circle_diameter"), top_hole_pattern.get("PCD"), top_hole_pattern.get("pcd"), top_hole_pattern.get("feature_placement", {}).get("diameter"))
        section_pcd = _first_numeric(section_hole_pattern.get("bolt_circle_diameter"), section_hole_pattern.get("PCD"), section_hole_pattern.get("pcd"))
        if isinstance(top_pcd, (int, float)) and isinstance(section_pcd, (int, float)):
            if not math.isclose(float(top_pcd), float(section_pcd), rel_tol=0.0, abs_tol=1e-6):
                issues.append("顶视与剖视的孔阵列直径不一致。")

        top_visible_face = top_hole_pattern.get("visible_on_face")
        section_start_face = section_hole_pattern.get("axial_start_face") or section_hole_pattern.get("start_face")
        if top_visible_face in {"recess_floor", "internal_floor", "lower_step_face"} and section_start_face == "top":
            issues.append("顶视已说明孔图元来自下层可见面，但剖视仍把孔起始面写成 top。")

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
    code_numbers = _collect_numeric_constants(code)
    section_view = _find_view(payload, "section")
    section_fillet = _as_dict(_find_entity(section_view, "fillet_inner") or _find_entity(section_view, "fillet_inner_step"))
    has_profile_round = any(token in code for token in ("threePointArc(", "radiusArc(", "sagittaArc("))

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

    for key in (
        "outer_diameter_flange",
        "outer_diameter_body",
        "inner_diameter_upper",
        "inner_diameter_bore",
        "recess_seat_diameter",
        "total_height",
        "lower_flange_height",
        "hole_count",
        "bolt_circle_diameter",
    ):
        if contract.get(key) is not None and not has_number(contract[key]):
            issues.append(f"代码缺少契约数值: {key}={contract[key]}。")

    if contract.get("middle_body_height") is not None and not (has_number(contract["middle_body_height"]) or derived_middle_height_ok):
        issues.append(f"代码缺少契约数值: middle_body_height={contract['middle_body_height']}。")

    if contract.get("upper_flange_height") is not None and not (has_number(contract["upper_flange_height"]) or derived_upper_height_ok):
        issues.append(f"代码缺少契约数值: upper_flange_height={contract['upper_flange_height']}。")

    if "exporters.export" not in code:
        issues.append("代码缺少 STEP 导出。")

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