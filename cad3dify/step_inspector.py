import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import cadquery as cq
from cadquery import exporters


def _round_float(value: float | int | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _load_step_model(step_filepath: str | Path) -> cq.Workplane:
    return cq.importers.importStep(str(Path(step_filepath).expanduser().resolve()))


def _bbox_dict(shape: Any) -> dict[str, Any]:
    bbox = shape.BoundingBox()
    return {
        "xmin_mm": _round_float(bbox.xmin),
        "ymin_mm": _round_float(bbox.ymin),
        "zmin_mm": _round_float(bbox.zmin),
        "xmax_mm": _round_float(bbox.xmax),
        "ymax_mm": _round_float(bbox.ymax),
        "zmax_mm": _round_float(bbox.zmax),
        "size_mm": {
            "x": _round_float(bbox.xlen),
            "y": _round_float(bbox.ylen),
            "z": _round_float(bbox.zlen),
        },
        "center_mm": {
            "x": _round_float((bbox.xmin + bbox.xmax) / 2.0),
            "y": _round_float((bbox.ymin + bbox.ymax) / 2.0),
            "z": _round_float((bbox.zmin + bbox.zmax) / 2.0),
        },
    }


def _axis_from_extents(extents: tuple[float, float, float]) -> str:
    axis_names = ("X", "Y", "Z")
    largest_index = max(range(3), key=lambda index: abs(extents[index]))
    return axis_names[largest_index]


def _plane_from_extents(extents: tuple[float, float, float], tolerance: float = 1e-4) -> str:
    axis_names = ("XY", "XZ", "YZ")
    smallest_index = min(range(3), key=lambda index: abs(extents[index]))
    if abs(extents[smallest_index]) > tolerance:
        return "oblique"
    return axis_names[smallest_index]


def _shape_lists(model: cq.Workplane) -> tuple[list[Any], list[Any], list[Any]]:
    solids = list(model.solids().vals())
    faces = list(model.faces().vals())
    edges = list(model.edges().vals())
    return solids, faces, edges


def _face_summary(faces: list[Any]) -> dict[str, Any]:
    face_types = Counter(str(face.geomType()).lower() for face in faces)
    cylinders_by_radius: dict[float, dict[str, Any]] = defaultdict(lambda: {"count": 0, "axes": Counter()})

    for face in faces:
        face_type = str(face.geomType()).lower()
        if face_type != "cylinder":
            continue
        bbox = face.BoundingBox()
        extents = (float(bbox.xlen), float(bbox.ylen), float(bbox.zlen))
        axis = _axis_from_extents(extents)
        try:
            radius = _round_float(face.radius())
        except Exception:
            radius = None
        radius_key = float(radius) if radius is not None else -1.0
        cylinders_by_radius[radius_key]["count"] += 1
        cylinders_by_radius[radius_key]["axes"][axis] += 1

    cylindrical_features = []
    for radius_key, payload in sorted(cylinders_by_radius.items(), key=lambda item: item[0]):
        cylindrical_features.append(
            {
                "radius_mm": None if radius_key < 0 else _round_float(radius_key),
                "count": payload["count"],
                "dominant_axis": payload["axes"].most_common(1)[0][0] if payload["axes"] else "unknown",
            }
        )

    return {
        "total": len(faces),
        "by_type": dict(sorted(face_types.items())),
        "cylindrical_features": cylindrical_features,
    }


def _edge_summary(edges: list[Any]) -> dict[str, Any]:
    edge_types = Counter(str(edge.geomType()).lower() for edge in edges)
    circles_by_plane_radius: dict[tuple[str, float], int] = defaultdict(int)

    for edge in edges:
        edge_type = str(edge.geomType()).lower()
        if edge_type != "circle":
            continue
        bbox = edge.BoundingBox()
        plane = _plane_from_extents((float(bbox.xlen), float(bbox.ylen), float(bbox.zlen)))
        try:
            radius = _round_float(edge.radius())
        except Exception:
            radius = None
        radius_key = float(radius) if radius is not None else -1.0
        circles_by_plane_radius[(plane, radius_key)] += 1

    circular_edges = []
    for (plane, radius_key), count in sorted(circles_by_plane_radius.items(), key=lambda item: (item[0][0], item[0][1])):
        circular_edges.append(
            {
                "plane": plane,
                "radius_mm": None if radius_key < 0 else _round_float(radius_key),
                "count": count,
            }
        )

    return {
        "total": len(edges),
        "by_type": dict(sorted(edge_types.items())),
        "circular_edges": circular_edges,
    }


def _orthographic_summary(bbox: dict[str, Any], edge_summary: dict[str, Any]) -> dict[str, Any]:
    size = bbox["size_mm"]
    circles_by_plane: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in edge_summary["circular_edges"]:
        circles_by_plane[item["plane"]].append(item)

    return {
        "top": {
            "projection_plane": "XY",
            "width_mm": size["x"],
            "height_mm": size["y"],
            "depth_axis": "Z",
            "circular_edges": circles_by_plane.get("XY", []),
        },
        "front": {
            "projection_plane": "XZ",
            "width_mm": size["x"],
            "height_mm": size["z"],
            "depth_axis": "Y",
            "circular_edges": circles_by_plane.get("XZ", []),
        },
        "right": {
            "projection_plane": "YZ",
            "width_mm": size["y"],
            "height_mm": size["z"],
            "depth_axis": "X",
            "circular_edges": circles_by_plane.get("YZ", []),
        },
    }


def export_orthographic_views(step_filepath: str | Path, output_dir: str | Path) -> dict[str, str]:
    model = _load_step_model(step_filepath)
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    views = {
        "top": (0, 0, 1),
        "front": (0, 1, 0),
        "right": (1, 0, 0),
    }
    exported: dict[str, str] = {}
    for name, projection_dir in views.items():
        target = output_path / f"{name}.svg"
        exporters.export(
            model,
            str(target),
            opt={"projectionDir": projection_dir, "showAxes": False, "showHidden": False},
        )
        exported[name] = str(target)
    return exported


def summarize_step(step_filepath: str | Path) -> dict[str, Any]:
    step_path = Path(step_filepath).expanduser().resolve()
    model = _load_step_model(step_path)
    root_shape = model.val()
    solids, faces, edges = _shape_lists(model)
    bbox = _bbox_dict(root_shape)
    face_summary = _face_summary(faces)
    edge_summary = _edge_summary(edges)

    try:
        volume_mm3 = _round_float(root_shape.Volume())
    except Exception:
        volume_mm3 = None

    return {
        "source": str(step_path),
        "solid_count": len(solids),
        "volume_mm3": volume_mm3,
        "bounding_box": bbox,
        "faces": face_summary,
        "edges": edge_summary,
        "orthographic_views": _orthographic_summary(bbox, edge_summary),
    }


def compare_step_summaries(left_summary: dict[str, Any], right_summary: dict[str, Any]) -> dict[str, Any]:
    left_bbox = left_summary["bounding_box"]["size_mm"]
    right_bbox = right_summary["bounding_box"]["size_mm"]
    left_faces = left_summary["faces"]["by_type"]
    right_faces = right_summary["faces"]["by_type"]
    left_edges = left_summary["edges"]["by_type"]
    right_edges = right_summary["edges"]["by_type"]

    return {
        "bbox_size_delta_mm": {
            axis: _round_float(float(left_bbox[axis]) - float(right_bbox[axis]))
            for axis in ("x", "y", "z")
        },
        "volume_delta_mm3": _round_float(
            (left_summary.get("volume_mm3") or 0.0) - (right_summary.get("volume_mm3") or 0.0)
        ),
        "solid_count_delta": int(left_summary.get("solid_count", 0)) - int(right_summary.get("solid_count", 0)),
        "face_type_delta": {
            face_type: int(left_faces.get(face_type, 0)) - int(right_faces.get(face_type, 0))
            for face_type in sorted(set(left_faces) | set(right_faces))
        },
        "edge_type_delta": {
            edge_type: int(left_edges.get(edge_type, 0)) - int(right_edges.get(edge_type, 0))
            for edge_type in sorted(set(left_edges) | set(right_edges))
        },
    }


def inspect_step(
    step_filepath: str | Path,
    compare_to: str | Path | None = None,
    export_views_dir: str | Path | None = None,
) -> dict[str, Any]:
    summary = summarize_step(step_filepath)
    result: dict[str, Any] = {"summary": summary}

    if compare_to is not None:
        reference = summarize_step(compare_to)
        result["reference_summary"] = reference
        result["comparison"] = compare_step_summaries(summary, reference)

    if export_views_dir is not None:
        result["exported_views"] = export_orthographic_views(step_filepath, export_views_dir)

    return result


def inspect_step_as_json(
    step_filepath: str | Path,
    compare_to: str | Path | None = None,
    export_views_dir: str | Path | None = None,
    indent: int = 2,
) -> str:
    return json.dumps(
        inspect_step(step_filepath, compare_to=compare_to, export_views_dir=export_views_dir),
        ensure_ascii=False,
        indent=indent,
    )