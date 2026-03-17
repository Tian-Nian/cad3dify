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
    "1. In section views, hatched regions represent solid material. Non-hatched enclosed regions represent voids, holes, grooves, bores, or removed material.\n"
    "2. Use the section view to determine which axial layer or face a cut feature starts from.\n"
    "3. Never default a patterned hole to the top face unless the section view positively supports that.\n"
    "4. When section A-A shows narrow unhatched vertical slots near the outer rim, determine their vertical span and map them to the matching flange layer.\n"
    "5. If the section view does not prove the axial layer, mark it unknown and explain the ambiguity briefly.\n"
    "6. In top views, distinguish visible openings from deeper hidden bores. Do not label a deeper bore as a visible top-view circle unless the drawing actually shows it.\n"
    "7. If a patterned hole opens from a recessed annular seat or step face, record that recessed start face explicitly instead of collapsing it to top or bottom.\n"
    "8. If the section shows a bottom chamfer, lower-edge relief, or other silhouette-only outer-edge feature, capture it as a separate chamfer or edge feature even when its exact size is uncertain.\n"
    "9. In top views, enumerate the visible concentric contours from outside to inside in order, and decide for each contour whether it is an outer silhouette, a visible opening, a recess boundary, or a hidden deeper feature inferred only from the section.\n"
    "10. In section views, decompose the part into axial bands or layers from datum face to opposite face. For every band, explicitly state outer boundary, inner boundary, and whether the annular region is solid or void.\n"
    "11. For every top-view hole pattern, recess ring, and visible circle, map it to the matching section layer, start face, or axial band. Do not leave the top/section correspondence implicit.\n"
    "12. For every enclosed region that matters to modeling, explicitly decide whether material is kept or removed. Never leave keep-vs-cut implicit in prose.\n"
    "13. Do not claim that a section view shows hole slots or drilled voids unless the cutting plane actually intersects the hole axes or the drawing explicitly depicts the holes in section. If the section misses the hole axes, use it only for layer inference, not direct hole shape evidence.\n"
    "14. Do not reuse a section diameter as a hole pitch-circle diameter unless the drawing explicitly dimensions the hole PCD. Visible contour diameters, recess diameters, and hole PCD are different concepts and must stay separate.\n"
    "15. A contour visible in the top view may belong to a lower internal face seen through an upper opening. Visibility from above does not mean the contour lies on the topmost face.\n"
    "16. For every visible top-view contour, record both why it is visible and which physical face owns it: top face, recessed floor, internal floor, lower step face, or another face.\n"
    "17. Distinguish these concepts explicitly whenever they appear: outer top rim, upper opening edge, lower exposed floor outer edge, lower exposed floor inner opening, and hole pattern visible on that lower floor.\n"
    "18. If a hole pattern is visible in top view through an upper opening but the section shows the cylinders start on a lower face, encode the visibility face and the true start face separately. Never collapse them into a top-face hole.\n"
    "19. A visible top-view circle can be an edge on a lower exposed face, not just a cut on the top face. Treat visibility provenance as part of the geometry, not as a note.\n"
    "20. Before finishing, check whether the top view mixes edges from multiple Z levels. If yes, keep those Z levels separate in JSON instead of flattening them into one plane.\n"
    "21. Use standardized names whenever the feature exists so downstream alignment stays stable: top-view ids `bolt_hole_pattern`, `central_bore`, `upper_opening`, `top_recess`; section-view ids `bolt_holes`, `central_bore`, `recessed_hole_seat`, `bottom_outer_chamfer`, `fillet_inner`; dimension labels `outer_diameter_flange`, `outer_diameter_body`, `inner_diameter_upper`, `inner_diameter_bore`, `recess_seat_diameter`, `total_height`, `lower_flange_height`, `middle_body_height`, `upper_flange_height`, `bolt_circle_diameter`.\n"
    "22. Never use an upper opening diameter, recess diameter, or body diameter as the bolt-circle diameter unless the drawing explicitly dimensions the hole center circle that way. In this drawing family, PCD belongs to hole centers only.\n"
    "23. If the hole center radius lies inside a larger visible top opening, those holes cannot belong to the outer top rim. They must belong to a lower visible face seen through that opening, or remain unknown if the drawing is ambiguous.\n"
    "24. Never infer an external outer-diameter step from an internal opening diameter. A diameter attached to an internal void or recess edge is not an outer profile diameter unless the section silhouette clearly shows an external vertical step at that diameter.\n"
    "25. If the drawing uses an R callout such as R2.00 on a profile transition, encode it as a fillet/round with explicit radius and explicit adjoining faces. Do not silently convert an explicit radius callout into a sharp step or a chamfer.\n"
    "26. Distinguish fillet/round from chamfer explicitly. An R-prefixed callout is a fillet unless the drawing explicitly labels a chamfer, bevel, or C-value.\n"
    "27. A rounded transition shown in section may connect two Z levels without creating an extra top-view contour. Preserve the round in section geometry and modeling instructions without inventing extra top-view circles.\n"
    "28. Keep the JSON compact and modeling-oriented. Avoid repeated prose.\n"
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
            "If a bolt-hole ring lies in a lower flange rather than the top flange, encode that in `feature_placement.target_layer` and `feature_placement.start_face`.\n"
            "If a bolt-hole ring is visible in top view on a lower exposed floor, keep two facts at once: `visible_on_face` is that lower exposed face, while `feature_placement.start_face` is the real drilling face from section.\n"
            "If the top view shows a large visible opening and the section shows a smaller deeper through bore, represent them as separate entities instead of merging them into one visible circle.\n"
            "If the holes sit on a recessed annular seat, use `start_face=upper_step` or `lower_step` as appropriate rather than `top` or `bottom`.\n"
            "If the top view contains circles from multiple Z levels, the JSON must keep them as separate contours with explicit face ownership rather than flattening them into one top plane.\n"
            "If the section silhouette shows a bottom chamfer, include an explicit chamfer entity and mention any missing size in `uncertainties`.\n"
            "If the drawing shows a rounded R transition between levels, do not replace it with a stepped corner in the JSON or modeling sequence.\n"
            "Make the JSON self-consistent across views: matching diameters, matching hole counts, matching PCDs, and matching axial interpretations.\n"
            "Before finishing, verify that the top-view contours and section-view bands together fully determine what is solid and what is removed.\n"
            "Never say the section directly shows a hole void unless the cutting plane intersects that hole pattern. If the section only provides indirect evidence for the hole layer, say so explicitly.\n"
            "Never collapse visible contour diameters, recess diameters, and hole PCD into one number unless the drawing explicitly says they are equal.\n"
            "Use the standardized ids and dimension labels from the rules above whenever those features exist.\n"
            "If you cannot prove the axial layer from the section view, set the hole placement fields to `unknown` and describe the ambiguity in `uncertainties` instead of guessing `top`.\n"
            "Keep `notes` minimal, usually empty or a single short item. Keep `axial_layer_reasoning` to one short sentence.\n"
            "Do not duplicate the same entity in multiple views unless the second view adds necessary axial information.\n"
            "Start now."
        )

        prompt = ChatPromptTemplate(
            input_variables=["image_type", "image_data"],
            messages=[
                HumanMessagePromptTemplate(
                    prompt=[
                        PromptTemplate(input_variables=[], template=analyze_prompt),
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
            input_variables=["image_type", "image_data"],
            output_variables=["result"],
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
            "Return JSON only using this schema:\n"
            f"{escaped_schema_text}\n"
            "Start now."
        )

        prompt = ChatPromptTemplate(
            input_variables=["image_type", "image_data"],
            messages=[
                HumanMessagePromptTemplate(
                    prompt=[
                        PromptTemplate(input_variables=[], template=analyze_prompt),
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
            input_variables=["image_type", "image_data"],
            output_variables=["result"],
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
        return inputs


class CadAnalysisRefinerChain(SequentialChain):
    model_type: MODEL_TYPE = "gpt"

    def __init__(self, model_type: MODEL_TYPE = "gpt") -> None:
        refine_analysis_prompt = (
            f"{_COMMON_ANALYSIS_RULES}"
            "You are repairing an analysis JSON so downstream CAD generation can run as a closed loop without manual edits.\n"
            "There is no human-edited fallback file in the loop. Your corrected JSON becomes the next source of truth for generation.\n"
            "Fix every listed validator issue while preserving explicit dimensions, cross-view mappings, and section semantics.\n"
            "Do not delete valid geometry just to silence an issue. Preserve explicit R callouts as real fillet features.\n"
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
            output_variables=["result"],
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