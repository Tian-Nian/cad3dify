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
from .spec_alignment import format_analysis_report, format_code_report, validate_analysis_payload, validate_generated_code
from .v1.cad_code_generator import CadCodeFromJsonGeneratorChain
from .v1.cad_code_refiner import CadCodeRefinerChain
from .v1.drawing_analyzer import CadAnalysisRefinerChain, CadDrawingAnalyzerChain, CadDrawingScopedAnalyzerChain

STAGES = ("analyze-drawing", "generate-code", "execute-code", "refine-code")


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
        return payload
    return _read_json(_analysis_file(workspace_dir, generated=generated))


def _agent_analysis_exists(workspace_dir: Path) -> bool:
    return _analysis_file(workspace_dir, generated=True).exists() or _analysis_parts_dir(workspace_dir, generated=True).exists()


def _load_agent_analysis_payload(workspace_dir: Path) -> dict:
    if _agent_analysis_exists(workspace_dir):
        return _load_analysis_payload(workspace_dir, generated=True)
    return _load_analysis_payload(workspace_dir, generated=False)


def _analysis_documents_text(workspace_dir: Path) -> str:
    payload = _load_agent_analysis_payload(workspace_dir)
    parts = [
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
    _write_json(_analysis_file(workspace_path, generated=True), payload)
    _write_analysis_parts(_analysis_parts_dir(workspace_path, generated=True), payload)


def _write_review_analysis_payload(workspace_path: Path, payload: dict) -> None:
    _write_json(_analysis_file(workspace_path, generated=False), payload)
    _write_analysis_parts(_analysis_parts_dir(workspace_path, generated=False), payload)


def _repair_analysis_until_aligned(
    workspace_path: Path,
    metadata: dict,
    initial_payload: dict,
    max_attempts: int = 2,
) -> dict:
    payload = initial_payload
    issues = validate_analysis_payload(payload)
    attempt = 0
    while issues and attempt < max_attempts:
        chain = CadAnalysisRefinerChain(model_type=metadata["model_type"])
        repaired = chain.invoke({"analysis_json": payload, "issues": issues})["result"]
        if not repaired:
            break
        payload = repaired
        issues = validate_analysis_payload(payload)
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
    result = chain.invoke(
        {
            "analysis_json": _analysis_documents_text(workspace_path),
            "code": current_code,
            "feedback": feedback,
        }
    )["result"]
    if not result:
        raise ValueError("CAD code refinement failed: model response did not contain parsable code.")

    return _repair_code_until_aligned(
        workspace_path=workspace_path,
        metadata=metadata,
        analysis_payload=analysis_payload,
        initial_code=result,
    )


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
        "source_image": str(copied_image),
        "output_filename": output_filename,
    }
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
            "Extract only the top view. First enumerate the visible concentric contours from outside to inside in `contour_stack`. For each contour, explicitly state which physical face owns that contour and why it is visible from above. Then encode each contour or pattern as geometry: outer silhouette, visible opening, recess boundary, lower-floor edge seen through an opening, hole-pattern reference, or hidden deeper feature inferred from section. Keep visible contour diameters separate from hole PCD. Use standardized ids when possible: `bolt_hole_pattern`, `central_bore`, `upper_opening`, `top_recess`. Use standardized diameter labels in `dimensions` when possible: `outer_diameter_flange`, `inner_diameter_upper`, `inner_diameter_bore`, `recess_seat_diameter`, `bolt_circle_diameter`. For each hole/cut/recess, include material_state, axial_extent, feature_placement, evidence, and the face on which it is visible. Never use the upper opening diameter or any profile diameter as the hole PCD unless the drawing explicitly dimensions the hole center circle that way. If the hole centers lie inside a larger visible top opening, the holes cannot belong to the outer top rim; assign them to a lower visible face or mark them unknown. If section data shows an R-radius transition between two levels, preserve that as a geometric note but do not invent an extra top-view contour unless the drawing actually shows one. Top-view output must be sufficient to reconstruct the plan-view footprint without guessing and without flattening multiple Z levels into one plane.",
        ),
        (
            "section_view",
            "{\n  \"name\": \"section_A-A\",\n  \"view_type\": \"section\",\n  \"summary\": \"\",\n  \"axial_bands\": [\n    {\n      \"band_id\": \"\",\n      \"band_role\": \"top_rim|upper_opening|internal_floor|middle_bore|lower_bore|solid_wall|unknown\",\n      \"axial_start\": null,\n      \"axial_end\": null,\n      \"outer_diameter\": null,\n      \"inner_diameter\": null,\n      \"annular_region\": \"solid|void|mixed|unknown\",\n      \"top_visibility\": \"visible_from_above|not_visible_from_above|hidden_but_dimensionally_required|unknown\",\n      \"evidence\": \"\"\n    }\n  ],\n  \"entities\": [],\n  \"dimensions\": [],\n  \"cross_view_mapping\": [],\n  \"notes\": []\n}",
            "Extract only the main section view. Decompose the cross-section into axial bands from datum face to opposite face in `axial_bands`. For each band, state OD, ID, whether the annular region is solid, void, or mixed, and whether that band creates edges visible from above. Use standardized ids when possible: `bolt_holes`, `central_bore`, `recessed_hole_seat`, `bottom_outer_chamfer`, `fillet_inner`. Use standardized dimension labels when possible: `outer_diameter_flange`, `outer_diameter_body`, `inner_diameter_upper`, `inner_diameter_bore`, `recess_seat_diameter`, `total_height`, `lower_flange_height`, `middle_body_height`, `upper_flange_height`, `bolt_circle_diameter`. Explicitly capture where every cut feature starts, whether a step face is recessed, and whether any outer-edge chamfer/relief exists. If the section dimensions an R-value at a transition, encode it as a fillet feature with exact radius and exact adjoining faces; do not simplify it into a step or label it a chamfer. Do not claim the section directly shows hole slots unless the cutting plane intersects them. If the section misses the hole axes, do not set `bolt_holes.start_face=top` just because the holes are visible in the top view. Never use a profile diameter like 129 or 105 as the hole PCD unless the drawing explicitly dimensions the hole center circle. Never turn an internal opening diameter into `outer_diameter_body` unless the section silhouette clearly shows an external OD step at that same diameter. Section output must be sufficient to reconstruct the full side/section profile without guessing and must explain which internal faces are visible from the top opening.",
        ),
        (
            "constraints",
            "{\n  \"global_constraints\": [],\n  \"modeling_sequence\": [],\n  \"uncertainties\": []\n}",
            "Extract only global constraints, modeling sequence, and uncertainties. Include explicit constraints that map top-view contour_stack items to section-view axial_bands, state separately whether each mapped region is kept material or removed material, call out any case where a top-view contour is visible through an upper opening but belongs to a lower internal face, and preserve any explicit R-radius transition as a real fillet requirement rather than allowing it to collapse into a step.",
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
        result = chain.invoke(image_data)["result"]
        if not result:
            raise ValueError(f"Drawing analysis failed for scope '{scope_name}': model response did not contain valid JSON.")
        scope_results[scope_name] = result

    result = {
        "drawing_summary": scope_results["summary"].get("drawing_summary", {}),
        "section_interpretation": scope_results["summary"].get("section_interpretation", {}),
        "views": [scope_results["top_view"], scope_results["section_view"]],
        "global_constraints": scope_results["constraints"].get("global_constraints", []),
        "modeling_sequence": scope_results["constraints"].get("modeling_sequence", []),
        "uncertainties": scope_results["constraints"].get("uncertainties", []),
    }

    analysis_issues = validate_analysis_payload(result)
    editable_result = result
    if analysis_issues:
        editable_result = _repair_analysis_until_aligned(workspace_path, metadata, result)
        analysis_issues = validate_analysis_payload(editable_result)

    generated_path = _analysis_file(workspace_path, generated=True)
    review_path = _analysis_file(workspace_path, generated=False)
    _write_agent_analysis_payload(workspace_path, editable_result)
    _write_review_analysis_payload(workspace_path, editable_result)
    _analysis_report_file(workspace_path).write_text(format_analysis_report(editable_result), encoding="utf-8")

    if analysis_issues:
        logger.warning("Analysis JSON has alignment issues; see report at {}", _analysis_report_file(workspace_path))

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
    while issues and attempt < max_attempts:
        feedback = "Validator mismatches to fix:\n" + "\n".join(f"- {issue}" for issue in issues)
        chain = CadCodeRefinerChain(model_type=metadata["model_type"])
        repaired = chain.invoke(
            {
                "analysis_json": _analysis_documents_text(workspace_path),
                "code": code,
                "feedback": feedback,
            }
        )["result"]
        if not repaired:
            break
        code = repaired
        issues = validate_generated_code(code, analysis_payload)
        attempt += 1
    return code


def run_generation_stage(workspace_dir: str) -> Path:
    workspace_path = Path(workspace_dir).expanduser().resolve()
    metadata = _load_metadata(workspace_path)
    if not _agent_analysis_exists(workspace_path) and not _analysis_file(workspace_path, generated=False).exists() and not _analysis_parts_dir(workspace_path, generated=False).exists():
        raise FileNotFoundError(f"Analysis JSON not found in {workspace_path}")

    chain = CadCodeFromJsonGeneratorChain(model_type=metadata["model_type"])
    analysis_documents = _analysis_documents_text(workspace_path)
    analysis_payload = _load_agent_analysis_payload(workspace_path)
    analysis_issues = validate_analysis_payload(analysis_payload)
    if analysis_issues:
        analysis_payload = _repair_analysis_until_aligned(workspace_path, metadata, analysis_payload)
        analysis_issues = validate_analysis_payload(analysis_payload)
        _write_agent_analysis_payload(workspace_path, analysis_payload)
        _write_review_analysis_payload(workspace_path, analysis_payload)
        analysis_documents = _analysis_documents_text(workspace_path)
    _analysis_report_file(workspace_path).write_text(format_analysis_report(analysis_payload), encoding="utf-8")
    if analysis_issues:
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


def run_execution_stage(workspace_dir: str, max_auto_repairs: int = 2) -> Path:
    workspace_path = Path(workspace_dir).expanduser().resolve()
    version = _latest_model_version(workspace_path)
    if version is None:
        raise FileNotFoundError("No agent-generated model file found. Run generate-code first.")
    metadata = _load_metadata(workspace_path)
    analysis_payload = _load_agent_analysis_payload(workspace_path)
    analysis_issues = validate_analysis_payload(analysis_payload)
    if analysis_issues:
        analysis_payload = _repair_analysis_until_aligned(workspace_path, metadata, analysis_payload)
        _write_agent_analysis_payload(workspace_path, analysis_payload)
        _write_review_analysis_payload(workspace_path, analysis_payload)

    attempt = 0
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

            logger.info(f"Execution succeeded. STEP file saved to {output_step}")
            logger.info(f"Execution log saved to {log_path}")
            return output_step

        if attempt >= max_auto_repairs:
            raise RuntimeError(f"Code execution failed after automatic repair attempts. See log: {log_path}")

        current_code = code_path.read_text(encoding="utf-8")
        feedback_sections = []
        if _feedback_file(workspace_path).exists():
            existing_feedback = _feedback_file(workspace_path).read_text(encoding="utf-8").strip()
            if existing_feedback:
                feedback_sections.append(existing_feedback)
        feedback_sections.append("## Automatic execution failure\n" + log_content.strip())
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
    if analysis_issues:
        analysis_payload = _repair_analysis_until_aligned(workspace_path, metadata, analysis_payload)
        analysis_issues = validate_analysis_payload(analysis_payload)
        _write_agent_analysis_payload(workspace_path, analysis_payload)
        _write_review_analysis_payload(workspace_path, analysis_payload)
        analysis_documents = _analysis_documents_text(workspace_path)
    _analysis_report_file(workspace_path).write_text(format_analysis_report(analysis_payload), encoding="utf-8")
    if analysis_issues:
        raise ValueError(
            "Analysis JSON still failed alignment checks after automatic repair. See report: "
            f"{_analysis_report_file(workspace_path)}"
        )
    current_code = _agent_model_file(workspace_path, version).read_text(encoding="utf-8")
    feedback = _feedback_file(workspace_path).read_text(encoding="utf-8") if _feedback_file(workspace_path).exists() else ""
    execution_log = _execution_log_file(workspace_path, version)
    if execution_log.exists():
        feedback = f"{feedback.strip()}\n\n## Latest execution log\n{execution_log.read_text(encoding='utf-8').strip()}".strip()

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
