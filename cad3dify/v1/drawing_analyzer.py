import json
import re
from typing import Any, Union

from langchain.chains import LLMChain, SequentialChain, TransformChain
from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, PromptTemplate
from langchain_core.prompts.image import ImagePromptTemplate

from ..chat_models import MODEL_TYPE, ChatModelParameters
from ..image import ImageData


_COMMON_ANALYSIS_RULES = (
    "You are a senior CAD drawing analyst. Analyze the attached 2D CAD drawing and return JSON only.\n"
    "The JSON will be reviewed and edited by a human, then used as the source of truth for later CAD code generation.\n"
    "Use millimeters for dimensions when the drawing implies mm. Keep uncertain values in an `uncertainties` array instead of inventing data.\n"
    "Critical interpretation rules:\n"
    "1. In section views, hatched regions represent solid material. Non-hatched enclosed regions represent voids, holes, grooves, bores, pockets, or removed material.\n"
    "2. Decompose the drawing into geometric primitives and relationships, not named part families. Focus on contours, openings, holes, slots, pockets, bosses, steps, fillets, chamfers, and their relative placement.\n"
    "3. For every meaningful entity, record relative position, local size, and ownership by a physical face or layer. If an absolute value is not dimensioned, keep the relation explicit instead of inventing a number.\n"
    "4. Use section views to determine axial layering, start faces, and keep-vs-cut semantics. If the section view does not prove the axial layer, mark it unknown and explain the ambiguity briefly.\n"
    "5. Never default a patterned hole, slot, or recess to the top face unless the section view positively supports that.\n"
    "6. In top views, distinguish visible openings from deeper hidden bores or cavities. Do not label a deeper feature as a visible top-view contour unless the drawing actually shows it.\n"
    "7. A contour visible in one view may belong to a lower internal face seen through an opening. Visibility does not imply the contour lies on the outermost face.\n"
    "8. For every visible contour, record both why it is visible and which physical face owns it. Treat visibility provenance as geometry, not as a side note.\n"
    "9. In top/front/side views, enumerate the visible contour stack from outside to inside or from one side to the other whenever that ordering matters for reconstruction.\n"
    "10. In section views, decompose the part into axial bands or layers from datum face to opposite face. For every band, explicitly state outer boundary, inner boundary, and whether the enclosed region is solid, void, or mixed.\n"
    "11. Map each visible contour, hole pattern, recess ring, or profile transition to the matching section band, face, or layer. Do not leave cross-view correspondence implicit.\n"
    "12. For every enclosed region that matters to modeling, explicitly decide whether material is kept or removed. Never leave keep-vs-cut implicit in prose.\n"
    "13. Do not claim that a section view directly shows a hole, slot, or drilled void unless the cutting plane intersects that feature or the drawing explicitly depicts it in section. Otherwise use the section only for layer inference.\n"
    "14. Keep contour diameters, profile widths, feature sizes, and pattern reference dimensions as separate concepts unless the drawing explicitly equates them. A reference pattern diameter is not automatically a material boundary.\n"
    "15. If the drawing shows repeated features, capture both the repeated feature geometry and the repetition rule: count, spacing, pitch circle, angular step, linear pitch, symmetry, or mirror relation.\n"
    "16. If a feature is visible in one view but starts from another face according to section evidence, encode the visibility face and the true start face separately.\n"
    "17. If the drawing uses an R callout on a profile transition, encode it as a fillet/round with explicit radius and adjoining geometry. Do not silently convert an explicit radius callout into a sharp step or chamfer.\n"
    "18. Distinguish fillet/round from chamfer explicitly. An R-prefixed callout is a fillet unless the drawing explicitly labels a chamfer, bevel, or C-value.\n"
    "19. A rounded transition shown in section may connect two layers without creating an extra contour in another view. Preserve the round in section geometry and modeling instructions without inventing extra visible edges.\n"
    "20. If a view mixes edges from multiple depth or Z levels, keep those levels separate in JSON instead of flattening them into one plane.\n"
    "21. Use stable semantic ids when the role is clear, such as `outer_profile`, `central_bore`, `hole_pattern_1`, `slot_array_1`, `recess_1`, `fillet_1`, or `chamfer_1`. Use generic numbered ids when the role is unclear.\n"
    "22. Use dimension labels tied to geometric meaning, not to guessed part families. Prefer labels like `overall_width`, `overall_height`, `overall_depth`, `outer_diameter`, `inner_diameter`, `pattern_pitch_circle_diameter`, `slot_width`, `wall_thickness`, `step_height`, or similarly specific semantic names when the drawing supports them.\n"
    "23. When dimensions are missing, preserve order, containment, adjacency, symmetry, tangency, concentricity, and alignment relationships explicitly so downstream modeling can still reconstruct the geometry.\n"
    "24. Keep the JSON compact and modeling-oriented. Avoid repeated prose.\n"
    "25. Determine `view_type` from projection semantics, not from sheet position. Do not call a front or side elevation `top` just because it is drawn above another view.\n"
    "26. For prismatic/support/bracket parts, explicitly capture the three global envelope axes. The true top view must describe the full plan-view footprint, while the section/elevation views must capture standing height and thickness/depth. If a view shows the full standing height together with a circular bore in true shape, that view is usually an elevation, not the plan view.\n"
)


_REPEATED_FEATURE_OUTPUT_RULES = (
    "Repeated-feature output contract:\n"
    "1. If the drawing shows a repeated feature array such as holes, slots, bosses, pockets, or similar repeated geometry, emit an explicit entity for that array rather than leaving it only in prose, notes, or global constraints.\n"
    "2. Each repeated-feature entity must carry the repetition rule fields that are actually supported by the drawing, such as count/quantity, pitch-circle diameter, linear pitch, angular step, symmetry, or seed feature size.\n"
    "3. Keep placement-reference dimensions separate from material-boundary dimensions. A pattern-reference diameter, pitch circle, spacing guide, or symmetry guide is not automatically an opening, boss diameter, recess boundary, or wall boundary.\n"
    "4. If a repeated feature is visible from one face but starts from another proven face or layer, encode `visible_on_face` and `feature_placement.start_face` separately instead of collapsing them into one fact.\n"
    "5. If a section, elevation, or detail view exists, represent the owning layer, support face, or support band for the repeated feature even when the cutting plane does not slice through every repeated instance directly.\n"
    "6. If a repeated feature is supported by a recessed floor, annular seat, pocket floor, side wall, or intermediate step, emit that supporting geometry as its own entity instead of merging it into the repeated feature.\n"
    "7. If validator issues mention a missing repeated-feature entity, missing quantity, missing start face, or confusion between reference dimensions and material boundaries, treat those as blocking and repair them explicitly before returning JSON.\n"
    "8. For repeated circular hole arrays, prefer the stable ids `bolt_hole_pattern` in the top view and `bolt_holes` in the section view because downstream normalization recognizes those names.\n"
)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    candidates = [fenced_match.group(1) if fenced_match else None, text]
    for candidate in candidates:
        if not candidate:
            continue
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or start >= end:
            continue
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            continue
    return None


def _parse_json(input: dict) -> dict:
    return {"result": _extract_json_object(input["text"])}


class CadDrawingAnalyzerChain(SequentialChain):
    model_type: MODEL_TYPE = "gpt"

    def __init__(self, model_type: MODEL_TYPE = "gpt") -> None:
        analyze_prompt = (
            f"{_COMMON_ANALYSIS_RULES}"
            f"{_REPEATED_FEATURE_OUTPUT_RULES}"
            "If validator issues are provided, treat them as missing-or-inconsistent information you must explicitly repair in the returned JSON.\n"
            "Return a complete structured JSON specification for the whole drawing.\n"
            "Use this JSON structure:\n"
            "{{\n"
            '  "drawing_summary": {{\n'
            '    "title": "",\n'
            '    "description": "",\n'
            '    "unit": "mm",\n'
            '    "assumptions": []\n'
            "  }},\n"
            '  "section_interpretation": {{\n'
            '    "hatched_regions_are_solid": true,\n'
            '    "unhatched_regions_are_void": true,\n'
            '    "datum_or_reference_face": "bottom|top|centerline|unknown",\n'
            '    "notes": []\n'
            "  }},\n"
            '  "views": [\n'
            "    {{\n"
            '      "name": "top_view",\n'
            '      "view_type": "top|front|side|section|detail|unknown",\n'
            '      "summary": "",\n'
            '      "contour_stack": [\n'
            "        {{\n"
            '          "order": 1,\n'
            '          "diameter": null,\n'
            '          "role": "outer_silhouette|visible_opening|recess_boundary|pattern_reference|hidden_only",\n'
            '          "material_state": "solid_boundary|void|transition|reference_only|unknown",\n'
            '          "visible_on_face": "top_face|recess_floor|internal_floor|lower_step_face|bottom_face|unknown",\n'
            '          "appearance_reason": "direct_edge_on_current_face|seen_through_upper_opening|hidden_only|unknown",\n'
            '          "owned_by_section_band": "",\n'
            '          "evidence": ""\n'
            "        }}\n"
            '      ],\n'
            '      "entities": [\n'
            "        {{\n"
            '          "id": "outer_profile|central_bore|bolt_hole_pattern|hole_pattern_1",\n'
            '          "type": "revolved_profile|through_hole|counterbore|annular_recess|annular_floor|hole_pattern|fillet|chamfer|slot_array|boss|unknown",\n'
            '          "name": "主体",\n'
            '          "shape": "",\n'
            '          "operation": "add|cut|unknown",\n'
            '          "material_state": "solid|void|unknown",\n'
            '          "visible_on_face": "top_face|recess_floor|internal_floor|lower_step_face|bottom_face|unknown",\n'
            '          "appearance_reason": "direct_edge_on_current_face|seen_through_upper_opening|hidden_only|unknown",\n'
            '          "position": {{\n'
            '            "xyz": [0.0, 0.0, 0.0],\n'
            '            "polar": {{"radius": 0.0, "angle_deg": 0.0, "reference": "global_origin"}}\n'
            "          }},\n"
            '          "axial_extent": {{\n'
            '            "start_z_mm": null,\n'
            '            "end_z_mm": null,\n'
            '            "start_reference": "bottom_face|top_face|upper_step_face|lower_step_face|center_plane|unknown",\n'
            '            "end_reference": "bottom_face|top_face|upper_step_face|lower_step_face|center_plane|unknown"\n'
            "          }},\n"
            '          "feature_placement": {{\n'
            '            "start_face": "top|bottom|upper_step|lower_step|side|unknown",\n'
            '            "cut_direction": "+Z|-Z|through|radial|unknown",\n'
            '            "target_layer": "upper_flange|lower_flange|middle_body|through_all|unknown"\n'
            "          }},\n"
            '          "evidence": {{\n'
            '            "primary_view": "top|section|front|side|detail|unknown",\n'
            '            "secondary_view": "top|section|front|side|detail|unknown",\n'
            '            "hatched_solid_support": false,\n'
            '            "unhatched_void_support": false,\n'
            '            "axial_layer_reasoning": ""\n'
            "          }},\n"
            '          "dimensions": {{\n'
            '            "diameter_mm": null,\n'
            '            "radius_mm": null,\n'
            '            "length_mm": null,\n'
            '            "width_mm": null,\n'
            '            "height_mm": null,\n'
            '            "thickness_mm": null,\n'
            '            "depth_mm": null\n'
            "          }},\n"
            '          "pattern": {{\n'
            '            "type": "none|circular|linear",\n'
            '            "count": null,\n'
            '            "pitch_circle_diameter_mm": null,\n'
            '            "angle_step_deg": null\n'
            "          }},\n"
            '          "notes": []\n'
            "        }}\n"
            "      ],\n"
            '      "axial_bands": [\n'
            "        {{\n"
            '          "band_id": "",\n'
            '          "band_role": "top_rim|upper_flange|middle_body|lower_flange|upper_opening|lower_bore|solid_wall|unknown",\n'
            '          "axial_start": null,\n'
            '          "axial_end": null,\n'
            '          "outer_diameter": null,\n'
            '          "inner_diameter": null,\n'
            '          "material_state": "solid|void|mixed|unknown",\n'
            '          "notes": []\n'
            "        }}\n"
            "      ],\n"
            '      "dimensions": [],\n'
            '      "cross_view_mapping": [\n'
            "        {{\n"
            '          "top_contour_order": 1,\n'
            '          "section_band_id": "",\n'
            '          "section_face": "top_face|recess_floor|internal_floor|lower_step_face|bottom_face|unknown",\n'
            '          "relationship": "same_edge|opening_to_band|edge_of_visible_floor|hole_on_visible_floor|hidden_bore|unknown"\n'
            "        }}\n"
            '      ],\n'
            '      "notes": []\n'
            "    }}\n"
            "  ],\n"
            '  "global_constraints": [],\n'
            '  "modeling_sequence": [],\n'
            '  "uncertainties": []\n'
            "}}\n"
            "If the drawing clearly contains repeated holes, slots, fillets, chamfers, bosses, pockets, or revolved profiles, capture them explicitly.\n"
            "If a section or detail view dimensions a radius on a profile transition, record that radius as a real fillet feature with its exact location and adjoining faces.\n"
            "For every hole, bore, slot, counterbore, groove, pocket, or recess, explicitly fill `material_state`, `axial_extent`, and `feature_placement`.\n"
            "For the top view, list all meaningful concentric contour circles in outside-to-inside order and explain whether each corresponds to outer material, a visible opening, a recess boundary, a lower-face edge seen through an opening, or a hidden deeper bore confirmed by section.\n"
            "For every visible top-view contour and entity, fill both `visible_on_face` and `appearance_reason`. If a contour is seen through an upper opening, say that explicitly instead of treating it as a top-face edge.\n"
            "For every patterned hole, explicitly fill `evidence`. If the section view does not clearly support top-face placement, do not assign `start_face=top`.\n"
            "For section views, add notes that explain which contours are solid because of hatching and which enclosed contours are void because they are not hatched.\n"
            "For section views, explicitly break the geometry into axial bands/layers and state for each band whether the annular region between OD and ID is solid or void.\n"
            "If a repeated cut or repeated boss lies in a lower flange, intermediate step, internal floor, or side wall rather than the outermost face, encode that in `feature_placement.target_layer` and `feature_placement.start_face`.\n"
            "If a repeated feature is visible in top view on a lower exposed floor, keep two facts at once: `visible_on_face` is that lower exposed face, while `feature_placement.start_face` is the true owning or drilling face inferred from section evidence.\n"
            "When a repeated feature array exists, the JSON is incomplete unless the relevant views and ownership layers are both represented.\n"
            "If only one view directly shows a repeated feature array, the other relevant view must still contain a matching entity inferred from cross-view reasoning rather than omitting it.\n"
            "Do not return a repeated feature array only as a contour, only as a note, or only inside `global_constraints`; it must be an entity with explicit repetition fields.\n"
            "If the drawing gives a repeated-feature count like 4x, 6x, or 12x, put that numeric value into the repeated-feature entity even if the individual instances are not all dimensioned separately.\n"
            "If the top view shows a large visible opening and the section shows a smaller deeper through bore, represent them as separate entities instead of merging them into one visible circle.\n"
            "If a repeated feature sits on a recessed annular seat, pocket floor, or intermediate step, use the appropriate owning face such as `upper_step`, `lower_step`, or another explicit support face rather than defaulting to `top` or `bottom`.\n"
            "If a repeated feature sits on a supporting floor or seat, also emit that supporting geometry with its own boundary dimensions. Do not substitute a pattern reference diameter for the support boundary diameter.\n"
            "Keep these dimensions distinct whenever the drawing supports them: outer envelope, internal opening, support boundary, repeated-feature reference dimension, and seed feature size.\n"
            "If the top view contains circles from multiple Z levels, the JSON must keep them as separate contours with explicit face ownership rather than flattening them into one top plane.\n"
            "If the section silhouette shows a bottom chamfer, include an explicit chamfer entity and mention any missing size in `uncertainties`.\n"
            "If the drawing shows a rounded R transition between levels, do not replace it with a stepped corner in the JSON or modeling sequence.\n"
            "Make the JSON self-consistent across views: matching diameters, matching hole counts, matching PCDs, and matching axial interpretations.\n"
            "For support brackets, pillow blocks, or other prismatic parts, do not collapse the model into a single upright plate. Make sure the JSON contains the full base footprint dimensions and the thickness/depth axis separately from the standing height axis.\n"
            "Before finishing, verify that the top-view contours and section-view bands together fully determine what is solid and what is removed.\n"
            "Never say the section directly shows a hole void unless the cutting plane intersects that hole pattern. If the section only provides indirect evidence for the hole layer, say so explicitly.\n"
            "Never collapse visible contour diameters, recess diameters, and hole PCD into one number unless the drawing explicitly says they are equal.\n"
            "Use the standardized ids and dimension labels from the rules above whenever those features exist.\n"
            "If you cannot prove the axial layer from the section view, set the hole placement fields to `unknown` and describe the ambiguity in `uncertainties` instead of guessing `top`.\n"
            "Keep `notes` minimal, usually empty or a single short item. Keep `axial_layer_reasoning` to one short sentence.\n"
            "Do not duplicate the same entity in multiple views unless the second view adds necessary axial information.\n"
            "## Validator Issues To Fix\n"
            "{review_issues}\n"
            "Start now."
        )

        prompt = ChatPromptTemplate(
            input_variables=["image_type", "image_data", "review_issues"],
            messages=[
                HumanMessagePromptTemplate(
                    prompt=[
                        PromptTemplate(input_variables=["review_issues"], template=analyze_prompt),
                        ImagePromptTemplate(
                            input_variables=["image_type", "image_data"],
                            template={"url": "data:image/{image_type};base64,{image_data}"},
                        ),
                    ]
                )
            ],
        )
        llm = ChatModelParameters.from_model_name(model_type).create_chat_model()

        super().__init__(
            chains=[
                LLMChain(prompt=prompt, llm=llm),  # type: ignore
                TransformChain(
                    input_variables=["text"],
                    output_variables=["result"],
                    transform=_parse_json,
                    atransform=None,
                ),
            ],
            input_variables=["image_type", "image_data", "review_issues"],
            output_variables=["text", "result"],
            verbose=True,
        )
        self.model_type = model_type

    def prep_inputs(self, inputs: Union[dict[str, Any], Any]) -> dict[str, str]:
        assert isinstance(inputs, ImageData) or (
            "input" in inputs and isinstance(inputs["input"], ImageData)
        ), "inputs must be ImageData or dict with 'input' and 'input' must be ImageData"
        if isinstance(inputs, ImageData):
            inputs = {"input": inputs}
        if self.model_type == "claude" and inputs["input"].type != "png":
            inputs["input"] = inputs["input"].convert("png")
        inputs["image_type"] = inputs["input"].media_type
        inputs["image_data"] = inputs["input"].data
        review_issues = inputs.get("review_issues", [])
        if isinstance(review_issues, list):
            review_issues = "\n".join(f"- {issue}" for issue in review_issues) if review_issues else "- No validator issues provided."
        inputs["review_issues"] = str(review_issues).strip() or "- No validator issues provided."
        return inputs


class CadDrawingScopedAnalyzerChain(SequentialChain):
    model_type: MODEL_TYPE = "gpt"

    def __init__(
        self,
        scope_name: str,
        schema_text: str,
        scope_instructions: str,
        model_type: MODEL_TYPE = "gpt",
    ) -> None:
        escaped_schema_text = schema_text.replace("{", "{{").replace("}", "}}")
        analyze_prompt = (
            f"{_COMMON_ANALYSIS_RULES}"
            f"Current scope: {scope_name}.\n"
            f"{scope_instructions}\n"
            "If validator issues are provided, use them to fill in missing or conflicting information for this scope.\n"
            "Return JSON only using this schema:\n"
            f"{escaped_schema_text}\n"
            "## Validator Issues To Fix\n"
            "{review_issues}\n"
            "Start now."
        )

        prompt = ChatPromptTemplate(
            input_variables=["image_type", "image_data", "review_issues"],
            messages=[
                HumanMessagePromptTemplate(
                    prompt=[
                        PromptTemplate(input_variables=["review_issues"], template=analyze_prompt),
                        ImagePromptTemplate(
                            input_variables=["image_type", "image_data"],
                            template={"url": "data:image/{image_type};base64,{image_data}"},
                        ),
                    ]
                )
            ],
        )
        llm = ChatModelParameters.from_model_name(model_type).create_chat_model()

        super().__init__(
            chains=[
                LLMChain(prompt=prompt, llm=llm),  # type: ignore
                TransformChain(
                    input_variables=["text"],
                    output_variables=["result"],
                    transform=_parse_json,
                    atransform=None,
                ),
            ],
            input_variables=["image_type", "image_data", "review_issues"],
            output_variables=["text", "result"],
            verbose=True,
        )
        self.model_type = model_type

    def prep_inputs(self, inputs: Union[dict[str, Any], Any]) -> dict[str, str]:
        assert isinstance(inputs, ImageData) or (
            "input" in inputs and isinstance(inputs["input"], ImageData)
        ), "inputs must be ImageData or dict with 'input' and 'input' must be ImageData"
        if isinstance(inputs, ImageData):
            inputs = {"input": inputs}
        if self.model_type == "claude" and inputs["input"].type != "png":
            inputs["input"] = inputs["input"].convert("png")
        inputs["image_type"] = inputs["input"].media_type
        inputs["image_data"] = inputs["input"].data
        review_issues = inputs.get("review_issues", [])
        if isinstance(review_issues, list):
            review_issues = "\n".join(f"- {issue}" for issue in review_issues) if review_issues else "- No validator issues provided."
        inputs["review_issues"] = str(review_issues).strip() or "- No validator issues provided."
        return inputs


class CadAnalysisRefinerChain(SequentialChain):
    model_type: MODEL_TYPE = "gpt"

    def __init__(self, model_type: MODEL_TYPE = "gpt") -> None:
        refine_analysis_prompt = (
            f"{_COMMON_ANALYSIS_RULES}"
            f"{_REPEATED_FEATURE_OUTPUT_RULES}"
            "You are repairing an analysis JSON so downstream CAD generation can run as a closed loop without manual edits.\n"
            "There is no human-edited fallback file in the loop. Your corrected JSON becomes the next source of truth for generation.\n"
            "Fix every listed validator issue while preserving explicit dimensions, cross-view mappings, and section semantics.\n"
            "Do not delete valid geometry just to silence an issue. Preserve explicit R callouts as real fillet features.\n"
            "Use the validator issues as the problem list for this specific drawing. Repair only the geometry relationships that the issues actually expose, instead of rewriting the JSON around one guessed part family.\n"
            "If the issues mention a missing repeated feature entity or missing quantity, add or repair an explicit repeated-feature entity rather than writing only notes or constraints.\n"
            "If the issues show that a reference dimension was confused with a material boundary, separate those concepts and restore the owning support geometry.\n"
            "If the issues show a visibility-face versus start-face mismatch, preserve both facts instead of collapsing them into one field.\n"
            "If one field remains ambiguous after repair, keep the entity and record the ambiguity in `uncertainties`; do not drop the entity.\n"
            "Return the full corrected JSON only.\n"
            "## Current Analysis JSON\n"
            "```json\n"
            "{analysis_json}\n"
            "```\n"
            "## Validator Issues\n"
            "{issues}\n"
            "## Start here\n"
            "Corrected JSON:"
        )
        prompt = ChatPromptTemplate(
            input_variables=["analysis_json", "issues"],
            messages=[
                HumanMessagePromptTemplate(
                    prompt=[
                        PromptTemplate(
                            input_variables=["analysis_json", "issues"],
                            template=refine_analysis_prompt,
                        )
                    ]
                )
            ],
        )
        llm = ChatModelParameters.from_model_name(model_type).create_chat_model()

        super().__init__(
            chains=[
                LLMChain(prompt=prompt, llm=llm),  # type: ignore
                TransformChain(
                    input_variables=["text"],
                    output_variables=["result"],
                    transform=_parse_json,
                    atransform=None,
                ),
            ],
            input_variables=prompt.input_variables,
            output_variables=["text", "result"],
            verbose=True,
        )
        self.model_type = model_type

    def prep_inputs(self, inputs: Union[dict[str, Any], Any]) -> dict[str, str]:
        assert "analysis_json" in inputs, "inputs must have 'analysis_json'"
        analysis_json = inputs["analysis_json"]
        if not isinstance(analysis_json, str):
            analysis_json = json.dumps(analysis_json, ensure_ascii=False, indent=2)
        issues = inputs.get("issues", [])
        if isinstance(issues, list):
            issues = "\n".join(f"- {issue}" for issue in issues) if issues else "- No validator issues provided."
        inputs["analysis_json"] = analysis_json
        inputs["issues"] = str(issues).strip() or "- No validator issues provided."
        return inputs