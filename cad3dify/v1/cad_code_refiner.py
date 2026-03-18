import json
from typing import Any, Union

from langchain.chains import LLMChain, SequentialChain, TransformChain
from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, PromptTemplate

from .cad_code_generator import _parse_code
from ..chat_models import MODEL_TYPE, ChatModelParameters


class CadCodeRefinerChain(SequentialChain):
    model_type: MODEL_TYPE = "gpt"

    def __init__(self, model_type: MODEL_TYPE = "gpt") -> None:
        refine_cad_code_prompt = (
            "You are a highly skilled CAD designer. You have a CAD specification JSON and the current CadQuery code.\n"
            "The JSON is the source of truth. Revise the code so the resulting STEP model matches the JSON specification as closely as possible.\n"
            "Treat the current code as the repair baseline, not as disposable draft text. Preserve all working geometry, dimensions, coordinate choices, variable names, and export behavior unless the feedback proves they are wrong.\n"
            "When execution feedback contains a traceback or assertion failure, fix that concrete failing operation first before making broader geometric changes. Do not replace the whole modeling strategy unless the current structure itself makes the fix impossible.\n"
            "Prefer the smallest coherent repair that removes the reported failure while keeping already-correct parts of the model intact.\n"
            "If the analysis bundle contains normalized_contract.json, treat it as the canonical resolved contract for final modeling dimensions and feature relationships.\n"
            "If raw per-view snippets conflict with normalized_contract.json, prefer normalized_contract.json because it already resolves cross-view ambiguity.\n"
            "Your corrected code will be checked by a strict validator for missing dimensions, missing features, wrong hole start face, and missing chamfer/fillet operations.\n"
            "If review notes or execution feedback are provided, incorporate them.\n"
            "Return the full corrected Python code inside a markdown code block.\n"
            "The corrected code must execute successfully. Prefer a simpler robust model over a more detailed but fragile one.\n"
            "There is no human patch step after this response. The closed loop will either execute this code directly or ask for another full corrected version.\n"
            "Even though you must return a full replacement program, it should behave like a targeted repair of the current code rather than a fresh rewrite.\n"
            "If the execution log shows a selector or fillet failure, replace it with a safer implementation such as a profile arc or constructive geometry. Do not omit an explicit, dimensioned fillet/chamfer unless the JSON itself marks it uncertain.\n"
            "If an explicit R fillet belongs to a revolved or section-defined profile transition, prefer rebuilding the profile with an arc over adding a fragile post-hoc edge fillet.\n"
            "Do not keep try/except branches that silently `pass` after a required fillet/chamfer fails. Replace the modeling strategy instead.\n"
            "Return one complete replacement program, not an incremental patch and not code that depends on hand-editing previous outputs.\n"
            "Do not keep dead exploratory code, duplicate rebuilds, or alternative branches that are not executed.\n"
            "If the latest failure is about detached solids, empty boolean targets, missing parents on the stack, or wrong solid count, repair the boolean ownership/fusion sequence in the current construction before attempting any wider redesign.\n"
            "Respect section semantics: hatched regions are solid, unhatched enclosed regions are void. If the JSON says a hole pattern belongs to a lower flange or lower layer, do not place it on the upper face.\n"
            "Preserve both view constraints simultaneously: the corrected model must match the top-view contour ordering and the section-view band/layer profile at the same time.\n"
            "If the JSON distinguishes visible openings, hidden deeper bores, recess boundaries, and solid annular rings, keep those distinctions in the geometry instead of merging them.\n"
            "If the JSON says some top-view contours or holes are visible on an internal floor through an upper opening, preserve that multi-level visibility. Do not rewrite them as if they live on the top face.\n"
            "If the JSON marks the axial layer of a hole as unknown, do not invent a top-face drilling operation unless the current code already has evidence for it. Prefer preserving ambiguity over introducing a wrong layer.\n"
            "If the JSON includes an explicit R-radius transition between levels, preserve it as a real fillet in the corrected geometry rather than flattening it into a step.\n"
            "When feedback lists validator mismatches, fix every listed mismatch explicitly.\n"
            "If feedback includes STEP comparison mismatches against a reference model, treat them as concrete evidence that the current geometry is oversimplified or missing layers/features. Repair those mismatches while staying consistent with the normalized contract.\n"
            "The final exported STEP must contain exactly one watertight fused solid unless the contract explicitly requires multiple disconnected bodies. Do not leave detached washers, islands, helper solids, or un-fused boolean remnants in the result.\n"
            "Preserve the reference coordinate frame when comparison feedback reveals a placement mismatch. For a symmetric flange-like part with total height 28 mm and reference center at Z=0, prefer modeling it around Z in the range -14..14 rather than shifting the whole body to 0..28 unless the contract explicitly requires a different datum.\n"
            "The main revolution / extrusion axis must stay aligned with global Z when the reference cylindrical features are Z-dominant. Do not accidentally build the part along X or Y.\n"
            "If the reference STEP exposes torus faces or explicit R-round transitions, do not replace them with sharp steps. Rebuild the 2D section profile with tangent arcs or apply a robust fillet strategy that survives execution.\n"
            "If a previous candidate matched overall size but still had large face/edge deficits, that means the model is missing real concentric layers, rounds, or hole depth structure. Add those missing layers instead of reusing the same simplified cylinder stack.\n"
            "Avoid speculative reinterpretation of resolved dimensions. If normalized_contract.json or comparison feedback indicates a known diameter, height, or start face, keep it fixed and repair topology/feature ownership around it.\n"
            "Geometry repair rules:\n"
            "- Keep reference geometry separate from real material boundaries. A pitch circle, datum, centerline, or alignment reference must not be turned into solid geometry by mistake.\n"
            "- If the current code collapses multiple depth levels or owning faces into one operation, rebuild the profile or construction sequence so each layer/face matches the JSON explicitly.\n"
            "- If the current code breaks containment, concentricity, tangency, symmetry, adjacency, or relative ordering described by the JSON, rebuild from those relationships instead of patching isolated dimensions.\n"
            "- If the section-defined profile is the clearest source of truth, prefer rebuilding the revolved or extruded profile from section bands over stacking ad hoc cylinders or boxes.\n"
            "- If the reference STEP exposes more cylindrical, toroidal, circular-edge, or annular-layer structure than the current model, prefer restoring the missing section-defined layers and rounds rather than adding arbitrary decorative detail.\n"
            "- If the current model produces the correct bounding-box size but wrong volume, wrong solid count, or far fewer circles/faces than the reference, assume the model is topologically too simple and rebuild the missing annular bands, counterbores, or rounds instead of tweaking only one number.\n"
            "## CAD Specification JSON\n"
            "```json\n"
            "{analysis_json}\n"
            "```\n"
            "## Code\n"
            "```python\n"
            "{code}\n"
            "```\n"
            "## Human Review Notes\n"
            "{feedback}\n"
            "## Start here\n"
            "Corrected code as one complete Python program only:"
        )
        prompt = ChatPromptTemplate(
            input_variables=["code", "analysis_json", "feedback"],
            messages=[
                HumanMessagePromptTemplate(
                    prompt=[
                        PromptTemplate(
                            input_variables=["code", "analysis_json", "feedback"],
                            template=refine_cad_code_prompt,
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
                    transform=_parse_code,
                    atransform=None,
                ),
            ],
            input_variables=prompt.input_variables,
            output_variables=["text", "result"],
            verbose=True,
        )
        self.model_type = model_type

    def prep_inputs(self, inputs: Union[dict[str, Any], Any]) -> dict[str, str]:
        assert (
            "analysis_json" in inputs
            and "code" in inputs
            and isinstance(inputs["code"], str)
        ), "inputs must have 'analysis_json' and 'code' keys"
        analysis_json = inputs["analysis_json"]
        if not isinstance(analysis_json, str):
            analysis_json = json.dumps(analysis_json, ensure_ascii=False, indent=2)
        inputs["analysis_json"] = analysis_json
        inputs["feedback"] = str(inputs.get("feedback", "")).strip() or "No additional human feedback provided."
        return inputs
