import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from string import Template

from loguru import logger

from .chat_models import MODEL_TYPE
from .image import ImageData
from .spec_alignment import build_contract, format_analysis_report, format_code_report, normalize_analysis_payload, validate_analysis_payload, validate_generated_code
from .step_inspector import inspect_step
from .v1.cad_code_generator import CadCodeFromJsonGeneratorChain
from .v1.cad_code_refiner import CadCodeRefinerChain
from .v1.drawing_analyzer import CadAnalysisRefinerChain, CadDrawingAnalyzerChain, CadDrawingScopedAnalyzerChain

STAGES = ("analyze-drawing", "generate-code", "execute-code", "refine-code")

NON_BLOCKING_ANALYSIS_ISSUES = {
    "顶视可见上开口直径与剖视上台阶孔直径不一致。",
}

REFINER_FORMAT_RETRY_NOTE = (
    "## Response format correction\n"
    "Your previous response did not yield a parsable Python program. Return exactly one complete CadQuery Python program inside a ```python fenced block. "
    "Do not include prose, bullet points, JSON, diff text, or commentary outside the code block."
)


def _write_json(filepath: Path, payload: dict) -> None:
    filepath.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(filepath: Path) -> dict:
    return json.loads(filepath.read_text(encoding="utf-8"))


def _metadata_file(workspace_dir: Path) -> Path:
    return workspace_dir / "workflow.json"


def _analysis_file(workspace_dir: Path, generated: bool = False) -> Path:
    return workspace_dir / ("analysis.generated.json" if generated else "analysis.json")


def _analysis_parts_dir(workspace_dir: Path, generated: bool = False) -> Path:
    return workspace_dir / ("analysis.generated.parts" if generated else "analysis.parts")


def _feedback_file(workspace_dir: Path) -> Path:
    return workspace_dir / "refine_feedback.txt"


def _analysis_report_file(workspace_dir: Path) -> Path:
    return workspace_dir / "analysis_alignment_report.txt"


def _step_inspection_file(workspace_dir: Path, version: int) -> Path:
    return workspace_dir / f"step_inspection_v{version:02d}.json"


def _step_inspection_views_dir(workspace_dir: Path, version: int) -> Path:
    return workspace_dir / f"step_inspection_v{version:02d}_views"


def _has_reference_comparison(inspection_payload: dict) -> bool:
    return isinstance(inspection_payload.get("comparison"), dict) and isinstance(inspection_payload.get("reference_summary"), dict)


def _step_comparison_issues(inspection_payload: dict) -> list[str]:
    comparison = inspection_payload.get("comparison") or {}
    issues: list[str] = []

    bbox_delta = comparison.get("bbox_size_delta_mm") or {}
    for axis in ("x", "y", "z"):
        value = bbox_delta.get(axis)
        if value is None:
            continue
        if abs(float(value)) > 1e-6:
            issues.append(f"Bounding-box size mismatch on {axis.upper()} axis: delta {float(value):.3f} mm.")

    volume_delta = comparison.get("volume_delta_mm3")
    if volume_delta is not None and abs(float(volume_delta)) > 1e-3:
        issues.append(f"Volume mismatch versus reference STEP: delta {float(volume_delta):.3f} mm^3.")

    solid_count_delta = comparison.get("solid_count_delta")
    if solid_count_delta is not None and int(solid_count_delta) != 0:
        issues.append(f"Solid-count mismatch versus reference STEP: delta {int(solid_count_delta)}.")

    face_delta = comparison.get("face_type_delta") or {}
    for face_type, value in sorted(face_delta.items()):
        if int(value) != 0:
            issues.append(f"Face-type count mismatch for {face_type}: delta {int(value)}.")

    edge_delta = comparison.get("edge_type_delta") or {}
    for edge_type, value in sorted(edge_delta.items()):
        if int(value) != 0:
            issues.append(f"Edge-type count mismatch for {edge_type}: delta {int(value)}.")

    summary = inspection_payload.get("summary") or {}
    reference_summary = inspection_payload.get("reference_summary") or {}

    summary_bbox = (summary.get("bounding_box") or {}).get("center_mm") or {}
    reference_bbox = (reference_summary.get("bounding_box") or {}).get("center_mm") or {}
    for axis in ("x", "y", "z"):
        current = summary_bbox.get(axis)
        reference = reference_bbox.get(axis)
        if current is None or reference is None:
            continue
        delta = float(current) - float(reference)
        if abs(delta) > 1e-6:
            issues.append(f"Bounding-box center mismatch on {axis.upper()} axis: delta {delta:.3f} mm.")

    summary_faces = (summary.get("faces") or {}).get("cylindrical_features") or []
    reference_faces = (reference_summary.get("faces") or {}).get("cylindrical_features") or []
    if summary_faces and reference_faces:
        current_axis = summary_faces[0].get("dominant_axis")
        reference_axis = reference_faces[0].get("dominant_axis")
        if current_axis and reference_axis and current_axis != reference_axis:
            issues.append(
                f"Dominant cylinder axis mismatch: current model is {current_axis}-dominant but reference is {reference_axis}-dominant."
            )

    summary_views = (summary.get("orthographic_views") or {})
    reference_views = (reference_summary.get("orthographic_views") or {})
    for view_name in ("top", "front", "right"):
        current_view = summary_views.get(view_name) or {}
        reference_view = reference_views.get(view_name) or {}
        current_circles = len(current_view.get("circular_edges") or [])
        reference_circles = len(reference_view.get("circular_edges") or [])
        if current_circles != reference_circles:
            issues.append(
                f"Orthographic {view_name} view exposes {current_circles} circular-edge groups, reference exposes {reference_circles}."
            )

    return issues


def _format_step_comparison_feedback(inspection_payload: dict) -> str:
    if not _has_reference_comparison(inspection_payload):
        return ""

    summary = inspection_payload.get("summary") or {}
    reference_summary = inspection_payload.get("reference_summary") or {}
    comparison = inspection_payload.get("comparison") or {}
    issues = _step_comparison_issues(inspection_payload)
    if not issues:
        return ""

    current_cyl_features = (summary.get("faces") or {}).get("cylindrical_features") or []
    reference_cyl_features = (reference_summary.get("faces") or {}).get("cylindrical_features") or []
    current_axis = current_cyl_features[0].get("dominant_axis") if current_cyl_features else None
    reference_axis = reference_cyl_features[0].get("dominant_axis") if reference_cyl_features else None
    reference_bbox_size = (reference_summary.get("bounding_box") or {}).get("size_mm") or {}

    repair_expectations = [
        "- Keep the normalized contract as the primary source of truth.",
        "- Use the reference STEP only to recover missing or oversimplified geometric layers, rounds, annular steps, hole depths, and repeated feature structure that remain compatible with the contract.",
        "- If the current model collapses multiple axial layers into one simple revolve, rebuild the section profile or constructive sequence so the resulting STEP exposes the missing faces and edges seen in the reference.",
        "- The next candidate must export exactly one fused solid and must not leave detached solids after boolean operations.",
        "- Keep the part aligned to the same global axis and center as the reference unless the normalized contract explicitly says otherwise.",
        "- If torus faces are missing in the comparison, rebuild the relevant round transitions as real arcs/fillets instead of leaving hard steps.",
    ]

    if current_axis and reference_axis and current_axis != reference_axis:
        repair_expectations.append(
            f"- The reference STEP is {reference_axis}-dominant for cylindrical features. Rebuild the main bore and hole operations along global {reference_axis}, not along global {current_axis}. Do not just rotate the finished body after modeling if that would move faces away from their owning layers."
        )

    if reference_bbox_size:
        repair_expectations.append(
            "- Use the reference global envelope as a hard coordinate-frame target: "
            f"X={reference_bbox_size.get('x', 'unknown')} mm, "
            f"Y={reference_bbox_size.get('y', 'unknown')} mm, "
            f"Z={reference_bbox_size.get('z', 'unknown')} mm. If your next candidate assigns the 369 mm overall height to Z instead of Y, the coordinate frame is still wrong."
        )

    bbox_delta = comparison.get("bbox_size_delta_mm") or {}
    if any(abs(float(bbox_delta.get(axis, 0.0))) > 1e-6 for axis in ("x", "y", "z")):
        repair_expectations.append(
            "- Treat large bounding-box axis deltas as a coordinate-frame or envelope-construction bug. Rebuild the part so the long overall height axis, base depth axis, and width axis land on the same global axes as the reference before adding secondary detail."
        )

    sections = [
        "## STEP comparison against reference",
        f"Generated STEP: {summary.get('source', 'unknown')}",
        f"Reference STEP: {reference_summary.get('source', 'unknown')}",
        f"Generated solid_count: {summary.get('solid_count', 'unknown')}",
        f"Reference solid_count: {reference_summary.get('solid_count', 'unknown')}",
        f"Generated bbox center: {json.dumps((summary.get('bounding_box') or {}).get('center_mm') or {}, ensure_ascii=False)}",
        f"Reference bbox center: {json.dumps((reference_summary.get('bounding_box') or {}).get('center_mm') or {}, ensure_ascii=False)}",
        "### Comparison summary",
        json.dumps(comparison, ensure_ascii=False, indent=2),
        "### Mismatches to fix",
        "\n".join(f"- {issue}" for issue in issues),
        "### Repair expectations",
        *repair_expectations,
    ]
    return "\n".join(sections)


def _blocking_analysis_issues(issues: list[str]) -> list[str]:
    return [issue for issue in issues if issue not in NON_BLOCKING_ANALYSIS_ISSUES]


def _invoke_analysis_json_chain_with_retries(
    chain,
    inputs: dict,
    description: str,
    max_attempts: int = 3,
) -> dict | None:
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            result = chain.invoke(inputs)["result"]
        except Exception as exc:  # pragma: no cover - exercised through pipeline tests via mocks
            last_error = exc
            logger.warning(
                "{} failed on attempt {}/{}: {}",
                description,
                attempt + 1,
                max_attempts,
                exc,
            )
            continue

        if result:
            return result

        logger.warning(
            "{} returned no valid JSON on attempt {}/{}.",
            description,
            attempt + 1,
            max_attempts,
        )

    if last_error is not None:
        logger.warning("{} exhausted retries after repeated upstream/model errors.", description)
    return None


def _code_report_file(workspace_dir: Path, version: int) -> Path:
    return workspace_dir / f"code_alignment_v{version:02d}.txt"


def _model_file(workspace_dir: Path, version: int, generated: bool = False) -> Path:
    suffix = ".generated" if generated else ""
    return workspace_dir / f"model_v{version:02d}{suffix}.py"


def _execution_log_file(workspace_dir: Path, version: int) -> Path:
    return workspace_dir / f"execution_v{version:02d}.log"


def _output_step_file(workspace_dir: Path, version: int) -> Path:
    return workspace_dir / f"output_v{version:02d}.step"


def _load_metadata(workspace_dir: Path) -> dict:
    metadata_path = _metadata_file(workspace_dir)
    if not metadata_path.exists():
        raise FileNotFoundError(f"Workflow metadata not found: {metadata_path}")
    return _read_json(metadata_path)


def _has_required_views(payload: dict) -> bool:
    views = payload.get("views", [])
    top_present = any(str(view.get("view_type", "")).lower() == "top" or str(view.get("name", "")).lower() == "top_view" for view in views)
    section_present = any(str(view.get("view_type", "")).lower() == "section" for view in views)
    return top_present and section_present


def _merge_analysis_with_fallback(primary: dict, fallback: dict) -> dict:
    if not primary.get("drawing_summary"):
        primary["drawing_summary"] = fallback.get("drawing_summary", {})
    if not primary.get("section_interpretation"):
        primary["section_interpretation"] = fallback.get("section_interpretation", {})
    primary_views = [view for view in primary.get("views", []) if isinstance(view, dict)]
    fallback_views = [view for view in fallback.get("views", []) if isinstance(view, dict)]
    if not primary_views:
        primary["views"] = fallback_views
    else:
        def _is_top_view(view: dict) -> bool:
            return str(view.get("view_type", "")).lower() == "top" or str(view.get("name", "")).lower() == "top_view"

        def _is_section_view(view: dict) -> bool:
            return str(view.get("view_type", "")).lower() == "section"

        has_top = any(_is_top_view(view) for view in primary_views)
        has_section = any(_is_section_view(view) for view in primary_views)

        for fallback_view in fallback_views:
            if _is_top_view(fallback_view) and not has_top:
                primary_views.append(fallback_view)
                has_top = True
            elif _is_section_view(fallback_view) and not has_section:
                primary_views.append(fallback_view)
                has_section = True

        primary["views"] = primary_views
    if not primary.get("global_constraints"):
        primary["global_constraints"] = fallback.get("global_constraints", [])
    if not primary.get("modeling_sequence"):
        primary["modeling_sequence"] = fallback.get("modeling_sequence", [])

    primary_uncertainties = primary.get("uncertainties", [])
    fallback_uncertainties = fallback.get("uncertainties", [])
    if fallback_uncertainties:
        primary["uncertainties"] = primary_uncertainties + [
            item for item in fallback_uncertainties if item not in primary_uncertainties
        ]
    return primary


def _detect_reference_step(source_path: Path) -> Path | None:
    for suffix in (".stp", ".step", ".STP", ".STEP"):
        candidate = source_path.with_suffix(suffix)
        if candidate.exists():
            return candidate.resolve()
    return None


def _run_step_inspection(workspace_path: Path, version: int, step_path: Path, metadata: dict) -> Path:
    reference_step_value = metadata.get("reference_step")
    reference_step = Path(reference_step_value).expanduser().resolve() if reference_step_value else None
    export_views_dir = _step_inspection_views_dir(workspace_path, version)
    result = inspect_step(
        step_filepath=step_path,
        compare_to=reference_step if reference_step and reference_step.exists() else None,
        export_views_dir=export_views_dir,
    )
    target = _step_inspection_file(workspace_path, version)
    _write_json(target, result)
    logger.info(f"STEP inspection saved to {target}")
    return target


def _load_step_inspection_payload(workspace_path: Path, version: int) -> dict | None:
    target = _step_inspection_file(workspace_path, version)
    if not target.exists():
        return None
    return _read_json(target)


def _write_analysis_parts(parts_dir: Path, payload: dict) -> None:
    parts_dir.mkdir(parents=True, exist_ok=True)
    views_dir = parts_dir / "views"
    views_dir.mkdir(parents=True, exist_ok=True)

    _write_json(parts_dir / "drawing_summary.json", payload.get("drawing_summary", {}))
    _write_json(parts_dir / "section_interpretation.json", payload.get("section_interpretation", {}))
    _write_json(parts_dir / "global_constraints.json", {"global_constraints": payload.get("global_constraints", [])})
    _write_json(parts_dir / "modeling_sequence.json", {"modeling_sequence": payload.get("modeling_sequence", [])})
    _write_json(parts_dir / "uncertainties.json", {"uncertainties": payload.get("uncertainties", [])})

    for view_path in views_dir.glob("*.json"):
        view_path.unlink()
    for index, view in enumerate(payload.get("views", []), start=1):
        view_name = view.get("name", f"view_{index}")
        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", view_name).strip("_") or f"view_{index}"
        _write_json(views_dir / f"{index:02d}_{safe_name}.json", view)


def _load_analysis_payload(workspace_dir: Path, generated: bool = False) -> dict:
    parts_dir = _analysis_parts_dir(workspace_dir, generated=generated)
    if parts_dir.exists():
        views_dir = parts_dir / "views"
        views = []
        if views_dir.exists():
            for view_file in sorted(views_dir.glob("*.json")):
                views.append(_read_json(view_file))
        payload = {
            "drawing_summary": _read_json(parts_dir / "drawing_summary.json") if (parts_dir / "drawing_summary.json").exists() else {},
            "section_interpretation": _read_json(parts_dir / "section_interpretation.json") if (parts_dir / "section_interpretation.json").exists() else {},
            "views": views,
            "global_constraints": _read_json(parts_dir / "global_constraints.json").get("global_constraints", []) if (parts_dir / "global_constraints.json").exists() else [],
            "modeling_sequence": _read_json(parts_dir / "modeling_sequence.json").get("modeling_sequence", []) if (parts_dir / "modeling_sequence.json").exists() else [],
            "uncertainties": _read_json(parts_dir / "uncertainties.json").get("uncertainties", []) if (parts_dir / "uncertainties.json").exists() else [],
        }
        return normalize_analysis_payload(payload)
    return normalize_analysis_payload(_read_json(_analysis_file(workspace_dir, generated=generated)))


def _agent_analysis_exists(workspace_dir: Path) -> bool:
    return _analysis_file(workspace_dir, generated=True).exists() or _analysis_parts_dir(workspace_dir, generated=True).exists()


def _load_agent_analysis_payload(workspace_dir: Path) -> dict:
    if _agent_analysis_exists(workspace_dir):
        return _load_analysis_payload(workspace_dir, generated=True)
    return _load_analysis_payload(workspace_dir, generated=False)


def _analysis_documents_text_from_payload(payload: dict) -> str:
    parts = [
        "## normalized_contract.json\n```json\n" + json.dumps(build_contract(payload), ensure_ascii=False, indent=2) + "\n```",
        "## drawing_summary.json\n```json\n" + json.dumps(payload.get("drawing_summary", {}), ensure_ascii=False, indent=2) + "\n```",
        "## section_interpretation.json\n```json\n" + json.dumps(payload.get("section_interpretation", {}), ensure_ascii=False, indent=2) + "\n```",
    ]
    for index, view in enumerate(payload.get("views", []), start=1):
        view_name = view.get("name", f"view_{index}")
        parts.append(f"## view_{index}_{view_name}.json\n```json\n" + json.dumps(view, ensure_ascii=False, indent=2) + "\n```")
    parts.append("## global_constraints.json\n```json\n" + json.dumps({"global_constraints": payload.get("global_constraints", [])}, ensure_ascii=False, indent=2) + "\n```")
    parts.append("## modeling_sequence.json\n```json\n" + json.dumps({"modeling_sequence": payload.get("modeling_sequence", [])}, ensure_ascii=False, indent=2) + "\n```")
    parts.append("## uncertainties.json\n```json\n" + json.dumps({"uncertainties": payload.get("uncertainties", [])}, ensure_ascii=False, indent=2) + "\n```")
    return "\n\n".join(parts)


def _analysis_documents_text(workspace_dir: Path) -> str:
    payload = _load_agent_analysis_payload(workspace_dir)
    return _analysis_documents_text_from_payload(payload)


def _force_output_filepath(code: str, output_path: Path) -> str:
    output_literal = str(output_path)
    patterns = [
        r'(exporters\.export\([^,]+,\s*["\"])' + r'([^"\']+\.step)' + r'(["\"])',
        r'(cq\.exporters\.export\([^,]+,\s*["\"])' + r'([^"\']+\.step)' + r'(["\"])',
    ]
    rewritten = code
    for pattern in patterns:
        rewritten, count = re.subn(pattern, rf'\1{output_literal}\3', rewritten)
        if count > 0:
            return rewritten
    return rewritten


def _write_agent_analysis_payload(workspace_path: Path, payload: dict) -> None:
    payload = normalize_analysis_payload(payload)
    _write_json(_analysis_file(workspace_path, generated=True), payload)
    _write_analysis_parts(_analysis_parts_dir(workspace_path, generated=True), payload)


def _write_review_analysis_payload(workspace_path: Path, payload: dict) -> None:
    payload = normalize_analysis_payload(payload)
    _write_json(_analysis_file(workspace_path, generated=False), payload)
    _write_analysis_parts(_analysis_parts_dir(workspace_path, generated=False), payload)


def _repair_analysis_until_aligned(
    workspace_path: Path,
    metadata: dict,
    initial_payload: dict,
    max_attempts: int = 6,
) -> dict:
    payload = normalize_analysis_payload(initial_payload)
    issues = validate_analysis_payload(payload)
    blocking_issues = _blocking_analysis_issues(issues)
    attempt = 0
    while blocking_issues and attempt < max_attempts:
        logger.warning(
            "Analysis alignment repair attempt {}/{} with {} blocking issues.",
            attempt + 1,
            max_attempts,
            len(blocking_issues),
        )
        chain = CadAnalysisRefinerChain(model_type=metadata["model_type"])
        repaired = _invoke_analysis_json_chain_with_retries(
            chain,
            {
                "analysis_json": _analysis_documents_text_from_payload(payload),
                "issues": blocking_issues,
            },
            description="Analysis alignment refiner",
        )
        if repaired:
            payload = normalize_analysis_payload(repaired)
            issues = validate_analysis_payload(payload)
            blocking_issues = _blocking_analysis_issues(issues)
            if not blocking_issues:
                break

        image_data = ImageData.load_from_file(metadata["source_image"])
        supplemented = _invoke_analysis_json_chain_with_retries(
            CadDrawingAnalyzerChain(model_type=metadata["model_type"]),
            {"input": image_data, "review_issues": blocking_issues},
            description="Fallback full-drawing analysis",
        )
        if supplemented:
            payload = normalize_analysis_payload(_merge_analysis_with_fallback(payload, supplemented))
        issues = validate_analysis_payload(payload)
        blocking_issues = _blocking_analysis_issues(issues)
        attempt += 1
    return payload


def _persist_code_version(workspace_path: Path, version: int, code: str, analysis_payload: dict) -> Path:
    output_step = _output_step_file(workspace_path, version)
    code = Template(code).substitute(output_filename=str(output_step))
    code = _force_output_filepath(code, output_step)
    generated_path = _model_file(workspace_path, version, generated=True)
    generated_path.write_text(code + "\n", encoding="utf-8")
    code_issues = validate_generated_code(code, analysis_payload)
    _code_report_file(workspace_path, version).write_text(format_code_report(code, analysis_payload), encoding="utf-8")
    if code_issues:
        raise ValueError(
            "CAD code generation failed alignment checks. See report: "
            f"{_code_report_file(workspace_path, version)}"
        )

    review_path = _model_file(workspace_path, version, generated=False)
    review_path.write_text(code + "\n", encoding="utf-8")
    return review_path


def _iter_model_versions(workspace_dir: Path) -> list[int]:
    versions = []
    for path in workspace_dir.glob("model_v*.py"):
        stem = path.stem.replace(".generated", "")
        try:
            versions.append(int(stem.split("_v", 1)[1]))
        except (IndexError, ValueError):
            continue
    return sorted(set(versions))


def _agent_model_file(workspace_dir: Path, version: int) -> Path:
    generated_path = _model_file(workspace_dir, version, generated=True)
    if generated_path.exists():
        return generated_path
    return _model_file(workspace_dir, version, generated=False)


def _refine_code_from_feedback(
    workspace_path: Path,
    metadata: dict,
    analysis_payload: dict,
    current_code: str,
    feedback: str,
) -> str:
    chain = CadCodeRefinerChain(model_type=metadata["model_type"])
    analysis_documents = _analysis_documents_text(workspace_path)
    result = _invoke_refiner_chain_with_retries(
        chain=chain,
        analysis_documents=analysis_documents,
        code=current_code,
        feedback=feedback,
    )
    if not result:
        raise ValueError("CAD code refinement failed: model response did not contain parsable code.")

    return _repair_code_until_aligned(
        workspace_path=workspace_path,
        metadata=metadata,
        analysis_payload=analysis_payload,
        initial_code=result,
    )


def _invoke_refiner_chain_with_retries(
    chain: CadCodeRefinerChain,
    analysis_documents: str,
    code: str,
    feedback: str,
    max_attempts: int = 3,
) -> str | None:
    retry_feedback = feedback.strip()
    for attempt in range(max_attempts):
        result = chain.invoke(
            {
                "analysis_json": analysis_documents,
                "code": code,
                "feedback": retry_feedback,
            }
        )["result"]
        if result:
            return result
        logger.warning("Refiner returned no parsable code block on attempt {}.", attempt + 1)
        retry_feedback = "\n\n".join(section for section in (retry_feedback, REFINER_FORMAT_RETRY_NOTE) if section.strip())
    return None


def _next_model_version(workspace_dir: Path) -> int:
    versions = _iter_model_versions(workspace_dir)
    return (max(versions) + 1) if versions else 1


def _latest_model_version(workspace_dir: Path) -> int | None:
    versions = _iter_model_versions(workspace_dir)
    return max(versions) if versions else None


def _detect_next_stage(workspace_dir: Path) -> str:
    if not _agent_analysis_exists(workspace_dir) and not _analysis_file(workspace_dir, generated=False).exists():
        return "analyze-drawing"
    version = _latest_model_version(workspace_dir)
    if version is None:
        return "generate-code"
    if not _output_step_file(workspace_dir, version).exists():
        return "execute-code"
    return "refine-code"


def _confirm_next_stage(stage_name: str, auto_approve: bool) -> bool:
    if auto_approve:
        return True
    answer = input(f"Stage '{stage_name}' completed. Continue to next stage? [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def initialize_workflow(
    image_filepath: str,
    workspace_dir: str,
    output_filename: str = "output.step",
    model_type: MODEL_TYPE = "gpt",
) -> Path:
    workspace_path = Path(workspace_dir).expanduser().resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)

    source_path = Path(image_filepath).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Image file not found: {source_path}")

    copied_image = workspace_path / f"input{source_path.suffix.lower()}"
    if source_path != copied_image:
        shutil.copy2(source_path, copied_image)

    metadata = {
        "model_type": model_type,
        "original_source_image": str(source_path),
        "source_image": str(copied_image),
        "output_filename": output_filename,
    }
    reference_step = _detect_reference_step(source_path)
    if reference_step is not None:
        metadata["reference_step"] = str(reference_step)
    _write_json(_metadata_file(workspace_path), metadata)

    if not _feedback_file(workspace_path).exists():
        _feedback_file(workspace_path).write_text(
            "# Add review notes here before running refine-code.\n",
            encoding="utf-8",
        )

    return workspace_path


def run_analysis_stage(workspace_dir: str) -> Path:
    workspace_path = Path(workspace_dir).expanduser().resolve()
    metadata = _load_metadata(workspace_path)
    image_data = ImageData.load_from_file(metadata["source_image"])
    scopes = [
        (
            "summary",
            "{\n  \"drawing_summary\": {\n    \"title\": \"\",\n    \"description\": \"\",\n    \"unit\": \"mm\",\n    \"assumptions\": []\n  },\n  \"section_interpretation\": {\n    \"hatched_regions_are_solid\": true,\n    \"unhatched_regions_are_void\": true,\n    \"datum_or_reference_face\": \"bottom|top|centerline|unknown\",\n    \"notes\": []\n  }\n}",
            "Extract only the drawing summary and the section interpretation. Record the key rule for this drawing: which visible areas are solid, which enclosed areas are void, and which face acts as the datum/reference for axial layering.",
        ),
        (
            "top_view",
            "{\n  \"name\": \"top_view\",\n  \"view_type\": \"top\",\n  \"summary\": \"\",\n  \"contour_stack\": [\n    {\n      \"order\": 1,\n      \"diameter\": null,\n      \"role\": \"outer_silhouette|visible_opening|recess_boundary|pattern_reference|hidden_only\",\n      \"material_state\": \"solid_boundary|void|transition|reference_only|unknown\",\n      \"visible_on_face\": \"top_face|recess_floor|internal_floor|lower_step_face|bottom_face|unknown\",\n      \"appearance_reason\": \"direct_edge_on_current_face|seen_through_upper_opening|hidden_only|unknown\",\n      \"owned_by_section_band\": \"\",\n      \"evidence\": \"\"\n    }\n  ],\n  \"entities\": [],\n  \"dimensions\": [],\n  \"cross_view_mapping\": [\n    {\n      \"top_contour_order\": 1,\n      \"section_band_id\": \"\",\n      \"section_face\": \"top_face|recess_floor|internal_floor|lower_step_face|bottom_face|unknown\",\n      \"relationship\": \"same_edge|opening_to_band|edge_of_visible_floor|hole_on_visible_floor|hidden_bore|unknown\"\n    }\n  ],\n  \"notes\": []\n}",
            "Extract only the top view. Enumerate the visible contour stack in `contour_stack` and preserve outside-to-inside ordering wherever it matters. For each contour, explicitly state which physical face owns that contour and why it is visible. Encode each contour or pattern as geometry such as outer silhouette, visible opening, recess boundary, reference pattern, or hidden deeper feature inferred from section. Keep reference dimensions like pitch circles separate from material boundaries. Use stable semantic ids when possible, but prefer geometric meaning over guessed part-family names. For each hole, cut, recess, boss, or repeated feature, include material_state, axial_extent, feature_placement, evidence, and the face on which it is visible. If multiple depth levels are visible in the same plan view, keep them as separate owned contours instead of flattening them into one plane. Preserve relative size, containment, symmetry, concentricity, and adjacency relationships even when some dimensions are not explicit. Top-view output must be sufficient to reconstruct the plan-view footprint without guessing. If the part is a bracket/support/prismatic body, the true top view must contain the full base footprint. A standing plate view with a circular bore shown in true shape is usually an elevation rather than the plan view; do not mislabel it as `top_view`.",
        ),
        (
            "section_view",
            "{\n  \"name\": \"section_A-A\",\n  \"view_type\": \"section\",\n  \"summary\": \"\",\n  \"axial_bands\": [\n    {\n      \"band_id\": \"\",\n      \"band_role\": \"top_rim|upper_opening|internal_floor|middle_bore|lower_bore|solid_wall|unknown\",\n      \"axial_start\": null,\n      \"axial_end\": null,\n      \"outer_diameter\": null,\n      \"inner_diameter\": null,\n      \"annular_region\": \"solid|void|mixed|unknown\",\n      \"top_visibility\": \"visible_from_above|not_visible_from_above|hidden_but_dimensionally_required|unknown\",\n      \"evidence\": \"\"\n    }\n  ],\n  \"entities\": [],\n  \"dimensions\": [],\n  \"cross_view_mapping\": [],\n  \"notes\": []\n}",
            "Extract only the main section view. Decompose the cross-section into axial bands from datum face to opposite face in `axial_bands`. For each band, state the outer boundary, inner boundary, whether the region is solid, void, or mixed, and whether that band creates edges visible from other views. Explicitly capture where every cut feature starts, whether a face is recessed, and whether any silhouette-only chamfer, relief, or round exists. If the section dimensions an R-value at a transition, encode it as a fillet feature with exact radius and adjoining geometry; do not simplify it into a step or label it a chamfer. Do not claim the section directly shows holes or slots unless the cutting plane intersects them. If the section misses a repeated feature axis, use the section for layer inference only. Preserve section-defined relative relationships such as wall thickness, offsets, coaxial steps, tangencies, and layer order. Section output must be sufficient to reconstruct the full profile without guessing and must explain which internal faces are visible through other openings. For bracket/support/prismatic parts, use the section to capture thickness/depth bands separately from the standing height axis, and keep any wider base footprint spans available for cross-view matching instead of collapsing them into the plate width.",
        ),
        (
            "constraints",
            "{\n  \"global_constraints\": [],\n  \"modeling_sequence\": [],\n  \"uncertainties\": []\n}",
            "Extract only global constraints, modeling sequence, and uncertainties. Include explicit constraints that map top-view contour_stack items to section-view axial_bands, state separately whether each mapped region is kept material or removed material, call out any case where a contour is visible through another opening but belongs to a deeper face, and preserve any explicit R-radius transition as a real fillet requirement rather than allowing it to collapse into a step. Prefer relation constraints such as concentricity, symmetry, tangency, equal spacing, alignment, containment, and ordering when they are visually evident even if some dimensions are missing.",
        ),
    ]
    scope_results = {}
    for scope_name, schema_text, scope_instructions in scopes:
        chain = CadDrawingScopedAnalyzerChain(
            scope_name=scope_name,
            schema_text=schema_text,
            scope_instructions=scope_instructions,
            model_type=metadata["model_type"],
        )
        result = _invoke_analysis_json_chain_with_retries(
            chain,
            image_data,
            description=f"Scoped analysis for '{scope_name}'",
        )
        if not result:
            logger.warning(
                "Scoped analysis for '{}' returned no valid JSON. Falling back to broader analysis for missing data.",
                scope_name,
            )
            continue
        scope_results[scope_name] = result

    summary_scope = scope_results.get("summary", {})
    constraints_scope = scope_results.get("constraints", {})

    result = {
        "drawing_summary": summary_scope.get("drawing_summary", {}),
        "section_interpretation": summary_scope.get("section_interpretation", {}),
        "views": [
            scope_results[scope_name]
            for scope_name in ("top_view", "section_view")
            if scope_name in scope_results
        ],
        "global_constraints": constraints_scope.get("global_constraints", []),
        "modeling_sequence": constraints_scope.get("modeling_sequence", []),
        "uncertainties": constraints_scope.get("uncertainties", []),
    }

    result = normalize_analysis_payload(result)
    if not _has_required_views(result):
        logger.warning("Scoped analysis did not yield required top/section views. Falling back to full-drawing analysis.")
        fallback_result = _invoke_analysis_json_chain_with_retries(
            CadDrawingAnalyzerChain(model_type=metadata["model_type"]),
            image_data,
            description="Initial full-drawing analysis fallback",
        )
        if fallback_result:
            result = normalize_analysis_payload(_merge_analysis_with_fallback(result, fallback_result))

    analysis_issues = validate_analysis_payload(result)
    editable_result = result
    if analysis_issues:
        editable_result = _repair_analysis_until_aligned(workspace_path, metadata, result)
        if not _has_required_views(editable_result):
            fallback_result = _invoke_analysis_json_chain_with_retries(
                CadDrawingAnalyzerChain(model_type=metadata["model_type"]),
                image_data,
                description="Post-repair full-drawing analysis fallback",
            )
            if fallback_result:
                editable_result = normalize_analysis_payload(_merge_analysis_with_fallback(editable_result, fallback_result))
        analysis_issues = validate_analysis_payload(editable_result)

    generated_path = _analysis_file(workspace_path, generated=True)
    review_path = _analysis_file(workspace_path, generated=False)
    _write_agent_analysis_payload(workspace_path, editable_result)
    _write_review_analysis_payload(workspace_path, editable_result)
    _analysis_report_file(workspace_path).write_text(format_analysis_report(editable_result), encoding="utf-8")

    if _blocking_analysis_issues(analysis_issues):
        logger.warning("Analysis JSON has alignment issues; see report at {}", _analysis_report_file(workspace_path))
        raise ValueError(
            "Analysis JSON still failed alignment checks after automatic repair. See report: "
            f"{_analysis_report_file(workspace_path)}"
        )

    logger.info(f"Saved agent-managed analysis JSON to {generated_path}")
    logger.info(f"Review copy of analysis JSON is available at {review_path}")
    return review_path


def _repair_code_until_aligned(
    workspace_path: Path,
    metadata: dict,
    analysis_payload: dict,
    initial_code: str,
    max_attempts: int = 2,
) -> str:
    code = initial_code
    issues = validate_generated_code(code, analysis_payload)
    attempt = 0
    analysis_documents = _analysis_documents_text(workspace_path)
    while issues and attempt < max_attempts:
        feedback = "Validator mismatches to fix:\n" + "\n".join(f"- {issue}" for issue in issues)
        chain = CadCodeRefinerChain(model_type=metadata["model_type"])
        repaired = _invoke_refiner_chain_with_retries(
            chain=chain,
            analysis_documents=analysis_documents,
            code=code,
            feedback=feedback,
        )
        if not repaired:
            break
        code = repaired
        issues = validate_generated_code(code, analysis_payload)
        attempt += 1
    return code


def _latest_step_comparison_feedback(workspace_path: Path, version: int) -> str:
    inspection_payload = _load_step_inspection_payload(workspace_path, version)
    if not inspection_payload:
        return ""
    return _format_step_comparison_feedback(inspection_payload)


def _execution_failure_guidance(log_content: str, current_code: str = "") -> str:
    combined_text = f"{log_content}\n{current_code}"
    guidance: list[str] = []

    if "unexpected keyword argument 'loftCombine'" in combined_text or "loftCombine=" in current_code:
        guidance.append(
            "- Do not call loft with loftCombine=... . In this CadQuery environment that keyword is unsupported. Use loft(ruled=True), loft(combine=True, ruled=True), or rebuild the transition with a simpler solid construction that executes on the current API."
        )

    if "Workplane object must have at least one solid on the stack to union!" in combined_text:
        guidance.append(
            "- Repair union ownership before changing dimensions. Every operand passed to union() must already contain a real solid on its stack. If an intersect(), loft(), or add() path may leave an empty workplane, re-wrap the actual solid first or fuse wrapped solids explicitly before continuing."
        )

    if "Cannot find a solid on the stack or in the parent chain" in combined_text:
        guidance.append(
            "- Repair the boolean target/cutter sequence before redesigning geometry. The object receiving cut()/intersect()/union() must already own a solid, and the cutter must also resolve to a solid. Do not switch onto a fresh construction workplane and then apply a boolean as if it were still attached to the previous solid."
        )

    if "Expected 1 solid, got" in combined_text:
        guidance.append(
            "- The next candidate must end with exactly one fused solid. Eliminate detached helper bodies, partial loft fragments, and multi-body leftovers before export."
        )

    if not guidance:
        return ""

    return "\n".join([
        "## Structured execution repair guidance",
        *guidance,
        "- Keep the existing dimensions and coordinate frame unless the failure proves they are wrong. Fix the invalid CadQuery operation sequence first.",
    ])


def run_generation_stage(workspace_dir: str) -> Path:
    workspace_path = Path(workspace_dir).expanduser().resolve()
    metadata = _load_metadata(workspace_path)
    if not _agent_analysis_exists(workspace_path) and not _analysis_file(workspace_path, generated=False).exists() and not _analysis_parts_dir(workspace_path, generated=False).exists():
        raise FileNotFoundError(f"Analysis JSON not found in {workspace_path}")

    chain = CadCodeFromJsonGeneratorChain(model_type=metadata["model_type"])
    analysis_documents = _analysis_documents_text(workspace_path)
    analysis_payload = _load_agent_analysis_payload(workspace_path)
    analysis_issues = validate_analysis_payload(analysis_payload)
    if _blocking_analysis_issues(analysis_issues):
        analysis_payload = _repair_analysis_until_aligned(workspace_path, metadata, analysis_payload)
        analysis_issues = validate_analysis_payload(analysis_payload)
        _write_agent_analysis_payload(workspace_path, analysis_payload)
        _write_review_analysis_payload(workspace_path, analysis_payload)
        analysis_documents = _analysis_documents_text(workspace_path)
    _analysis_report_file(workspace_path).write_text(format_analysis_report(analysis_payload), encoding="utf-8")
    if _blocking_analysis_issues(analysis_issues):
        raise ValueError(
            "Analysis JSON still failed alignment checks after automatic repair. See report: "
            f"{_analysis_report_file(workspace_path)}"
        )
    result = chain.invoke({"analysis_json": analysis_documents})["result"]
    if not result:
        raise ValueError("CAD code generation failed: model response did not contain parsable code.")

    result = _repair_code_until_aligned(
        workspace_path=workspace_path,
        metadata=metadata,
        analysis_payload=analysis_payload,
        initial_code=result,
    )

    version = _next_model_version(workspace_path)
    review_path = _persist_code_version(workspace_path, version, result, analysis_payload)

    logger.info(f"Saved agent-generated CAD code to {_model_file(workspace_path, version, generated=True)}")
    logger.info(f"Review copy of CAD code is available at {review_path}")
    return review_path


def run_execution_stage(workspace_dir: str, max_auto_repairs: int = 4, max_refinement_cycles: int = 2) -> Path:
    workspace_path = Path(workspace_dir).expanduser().resolve()
    version = _latest_model_version(workspace_path)
    if version is None:
        raise FileNotFoundError("No agent-generated model file found. Run generate-code first.")
    metadata = _load_metadata(workspace_path)
    analysis_payload = _load_agent_analysis_payload(workspace_path)
    analysis_issues = validate_analysis_payload(analysis_payload)
    if _blocking_analysis_issues(analysis_issues):
        analysis_payload = _repair_analysis_until_aligned(workspace_path, metadata, analysis_payload)
        _write_agent_analysis_payload(workspace_path, analysis_payload)
        _write_review_analysis_payload(workspace_path, analysis_payload)

    attempt = 0
    refinement_cycle = 0
    while True:
        code_path = _agent_model_file(workspace_path, version)
        output_step = _output_step_file(workspace_path, version)
        log_path = _execution_log_file(workspace_path, version)

        completed = subprocess.run(
            [sys.executable, str(code_path)],
            cwd=str(workspace_path),
            capture_output=True,
            text=True,
        )
        log_content = (
            f"Command: {sys.executable} {code_path.name}\n"
            f"Return code: {completed.returncode}\n\n"
            "[stdout]\n"
            f"{completed.stdout}\n\n"
            "[stderr]\n"
            f"{completed.stderr}\n"
        )
        log_path.write_text(log_content, encoding="utf-8")

        if completed.returncode == 0 and output_step.exists():
            final_output = workspace_path / metadata["output_filename"]
            if final_output != output_step:
                shutil.copy2(output_step, final_output)

            inspection_path = _run_step_inspection(workspace_path, version, output_step, metadata)
            inspection_payload = _read_json(inspection_path)
            comparison_feedback = _format_step_comparison_feedback(inspection_payload)
            if comparison_feedback:
                if attempt >= max_auto_repairs:
                    if refinement_cycle >= max_refinement_cycles:
                        raise RuntimeError(
                            "STEP execution succeeded but the result still differs from the reference STEP after automatic repair attempts. "
                            f"See inspection report: {inspection_path}"
                        )

                    logger.warning(
                        "Execution comparison still fails after {} inline repair attempts; rolling back to refine-code (cycle {}/{}).",
                        attempt,
                        refinement_cycle + 1,
                        max_refinement_cycles,
                    )
                    run_refinement_stage(str(workspace_path))
                    version = _latest_model_version(workspace_path)
                    if version is None:
                        raise RuntimeError("Refinement rollback did not produce a new model version.")
                    attempt = 0
                    refinement_cycle += 1
                    continue

                current_code = code_path.read_text(encoding="utf-8")
                feedback_sections = []
                if _feedback_file(workspace_path).exists():
                    existing_feedback = _feedback_file(workspace_path).read_text(encoding="utf-8").strip()
                    if existing_feedback:
                        feedback_sections.append(existing_feedback)
                code_report_path = _code_report_file(workspace_path, version)
                if code_report_path.exists():
                    feedback_sections.append("## Latest validator report\n" + code_report_path.read_text(encoding="utf-8").strip())
                feedback_sections.append(comparison_feedback)

                refined_code = _refine_code_from_feedback(
                    workspace_path=workspace_path,
                    metadata=metadata,
                    analysis_payload=analysis_payload,
                    current_code=current_code,
                    feedback="\n\n".join(section for section in feedback_sections if section.strip()),
                )

                version = _next_model_version(workspace_path)
                _persist_code_version(workspace_path, version, refined_code, analysis_payload)
                attempt += 1
                continue

            logger.info(f"Execution succeeded. STEP file saved to {output_step}")
            logger.info(f"Execution log saved to {log_path}")
            return output_step

        if attempt >= max_auto_repairs:
            if refinement_cycle >= max_refinement_cycles:
                raise RuntimeError(f"Code execution failed after automatic repair attempts. See log: {log_path}")

            logger.warning(
                "Code execution still fails after {} inline repair attempts; rolling back to refine-code (cycle {}/{}).",
                attempt,
                refinement_cycle + 1,
                max_refinement_cycles,
            )
            run_refinement_stage(str(workspace_path))
            version = _latest_model_version(workspace_path)
            if version is None:
                raise RuntimeError("Refinement rollback did not produce a new model version.")
            attempt = 0
            refinement_cycle += 1
            continue

        current_code = code_path.read_text(encoding="utf-8")
        feedback_sections = []
        if _feedback_file(workspace_path).exists():
            existing_feedback = _feedback_file(workspace_path).read_text(encoding="utf-8").strip()
            if existing_feedback:
                feedback_sections.append(existing_feedback)
        feedback_sections.append("## Automatic execution failure\n" + log_content.strip())
        execution_guidance = _execution_failure_guidance(log_content, current_code)
        if execution_guidance:
            feedback_sections.append(execution_guidance)
        code_report_path = _code_report_file(workspace_path, version)
        if code_report_path.exists():
            feedback_sections.append("## Latest validator report\n" + code_report_path.read_text(encoding="utf-8").strip())

        refined_code = _refine_code_from_feedback(
            workspace_path=workspace_path,
            metadata=metadata,
            analysis_payload=analysis_payload,
            current_code=current_code,
            feedback="\n\n".join(section for section in feedback_sections if section.strip()),
        )

        version = _next_model_version(workspace_path)
        _persist_code_version(workspace_path, version, refined_code, analysis_payload)
        attempt += 1


def run_refinement_stage(workspace_dir: str) -> Path:
    workspace_path = Path(workspace_dir).expanduser().resolve()
    metadata = _load_metadata(workspace_path)
    version = _latest_model_version(workspace_path)
    if version is None:
        raise FileNotFoundError("No agent-generated model file found. Run generate-code first.")

    analysis_documents = _analysis_documents_text(workspace_path)
    analysis_payload = _load_agent_analysis_payload(workspace_path)
    analysis_issues = validate_analysis_payload(analysis_payload)
    if _blocking_analysis_issues(analysis_issues):
        analysis_payload = _repair_analysis_until_aligned(workspace_path, metadata, analysis_payload)
        analysis_issues = validate_analysis_payload(analysis_payload)
        _write_agent_analysis_payload(workspace_path, analysis_payload)
        _write_review_analysis_payload(workspace_path, analysis_payload)
        analysis_documents = _analysis_documents_text(workspace_path)
    _analysis_report_file(workspace_path).write_text(format_analysis_report(analysis_payload), encoding="utf-8")
    if _blocking_analysis_issues(analysis_issues):
        raise ValueError(
            "Analysis JSON still failed alignment checks after automatic repair. See report: "
            f"{_analysis_report_file(workspace_path)}"
        )
    current_code = _agent_model_file(workspace_path, version).read_text(encoding="utf-8")
    feedback = _feedback_file(workspace_path).read_text(encoding="utf-8") if _feedback_file(workspace_path).exists() else ""
    execution_log = _execution_log_file(workspace_path, version)
    if execution_log.exists():
        execution_log_text = execution_log.read_text(encoding="utf-8").strip()
        feedback = f"{feedback.strip()}\n\n## Latest execution log\n{execution_log_text}".strip()
        execution_guidance = _execution_failure_guidance(execution_log_text, current_code)
        if execution_guidance:
            feedback = f"{feedback.strip()}\n\n{execution_guidance}".strip()
    comparison_feedback = _latest_step_comparison_feedback(workspace_path, version)
    if comparison_feedback:
        feedback = f"{feedback.strip()}\n\n{comparison_feedback}".strip()

    result = _refine_code_from_feedback(
        workspace_path=workspace_path,
        metadata=metadata,
        analysis_payload=analysis_payload,
        current_code=current_code,
        feedback=feedback,
    )

    next_version = _next_model_version(workspace_path)
    review_path = _persist_code_version(workspace_path, next_version, result, analysis_payload)

    logger.info(f"Saved refined CAD code to {_model_file(workspace_path, next_version, generated=True)}")
    logger.info(f"Review copy of refined CAD code is available at {review_path}")
    return review_path


def generate_step_from_2d_cad_image(
    image_filepath: str,
    output_filepath: str,
    num_refinements: int = 0,
    model_type: MODEL_TYPE = "gpt",
    workspace_dir: str | None = None,
    auto_approve: bool = True,
) -> None:
    output_path = Path(output_filepath).expanduser().resolve()
    workspace_path = (
        Path(workspace_dir).expanduser().resolve()
        if workspace_dir
        else output_path.parent / f"{output_path.stem}_workflow"
    )

    initialize_workflow(
        image_filepath=image_filepath,
        workspace_dir=str(workspace_path),
        output_filename=output_path.name,
        model_type=model_type,
    )
    run_analysis_stage(str(workspace_path))
    if not _confirm_next_stage("analyze-drawing", auto_approve):
        return
    run_generation_stage(str(workspace_path))
    if not _confirm_next_stage("generate-code", auto_approve):
        return
    run_execution_stage(str(workspace_path))

    for _ in range(num_refinements):
        if not _confirm_next_stage("execute-code", auto_approve):
            return
        run_refinement_stage(str(workspace_path))
        if not _confirm_next_stage("refine-code", auto_approve):
            return
        run_execution_stage(str(workspace_path))

    latest_version = _latest_model_version(workspace_path)
    if latest_version is not None:
        latest_step = _output_step_file(workspace_path, latest_version)
        if latest_step.exists() and latest_step != output_path:
            shutil.copy2(latest_step, output_path)


def continue_workflow(workspace_dir: str, auto_approve: bool = False, until_stage: str = "execute-code") -> None:
    if until_stage not in STAGES:
        raise ValueError(f"Invalid stage: {until_stage}")

    workspace_path = Path(workspace_dir).expanduser().resolve()
    handlers = {
        "analyze-drawing": run_analysis_stage,
        "generate-code": run_generation_stage,
        "execute-code": run_execution_stage,
        "refine-code": run_refinement_stage,
    }
    start_stage = _detect_next_stage(workspace_path)
    start_index = STAGES.index(start_stage)
    end_index = STAGES.index(until_stage)
    if end_index < start_index:
        end_index = start_index

    for stage in STAGES[start_index : end_index + 1]:
        handlers[stage](workspace_dir)
        if stage == until_stage:
            break
        if not _confirm_next_stage(stage, auto_approve):
            break


def run_single_stage(workspace_dir: str, stage: str) -> Path:
    handlers = {
        "analyze-drawing": run_analysis_stage,
        "generate-code": run_generation_stage,
        "execute-code": run_execution_stage,
        "refine-code": run_refinement_stage,
    }
    if stage not in handlers:
        raise ValueError(f"Invalid stage: {stage}")
    return handlers[stage](workspace_dir)
