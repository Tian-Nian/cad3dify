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
            "Your corrected code will be checked by a strict validator for missing dimensions, missing features, wrong hole start face, and missing chamfer/fillet operations.\n"
            "If review notes or execution feedback are provided, incorporate them.\n"
            "Return the full corrected Python code inside a markdown code block.\n"
            "The corrected code must execute successfully. Prefer a simpler robust model over a more detailed but fragile one.\n"
            "There is no human patch step after this response. The closed loop will either execute this code directly or ask for another full corrected version.\n"
            "If the execution log shows a selector or fillet failure, replace it with a safer implementation such as a profile arc or constructive geometry. Do not omit an explicit, dimensioned fillet/chamfer unless the JSON itself marks it uncertain.\n"
            "If an explicit R fillet belongs to a revolved or section-defined profile transition, prefer rebuilding the profile with an arc over adding a fragile post-hoc edge fillet.\n"
            "Do not keep try/except branches that silently `pass` after a required fillet/chamfer fails. Replace the modeling strategy instead.\n"
            "Return one complete replacement program, not an incremental patch and not code that depends on hand-editing previous outputs.\n"
            "Do not keep dead exploratory code, duplicate rebuilds, or alternative branches that are not executed.\n"
            "Respect section semantics: hatched regions are solid, unhatched enclosed regions are void. If the JSON says a hole pattern belongs to a lower flange or lower layer, do not place it on the upper face.\n"
            "Preserve both view constraints simultaneously: the corrected model must match the top-view contour ordering and the section-view band/layer profile at the same time.\n"
            "If the JSON distinguishes visible openings, hidden deeper bores, recess boundaries, and solid annular rings, keep those distinctions in the geometry instead of merging them.\n"
            "If the JSON says some top-view contours or holes are visible on an internal floor through an upper opening, preserve that multi-level visibility. Do not rewrite them as if they live on the top face.\n"
            "If the JSON marks the axial layer of a hole as unknown, do not invent a top-face drilling operation unless the current code already has evidence for it. Prefer preserving ambiguity over introducing a wrong layer.\n"
            "If the JSON includes an explicit R-radius transition between levels, preserve it as a real fillet in the corrected geometry rather than flattening it into a step.\n"
            "When feedback lists validator mismatches, fix every listed mismatch explicitly.\n"
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
            "Corrected code:"
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
            output_variables=["result"],
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
