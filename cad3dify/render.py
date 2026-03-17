import os
import tempfile

import cadquery as cq
from cadquery import exporters
from reportlab.graphics import renderPM
from svglib.svglib import svg2rlg


def render_and_export_image(cat_filepath: str | os.PathLike[str], output_filepath: str | os.PathLike[str]):
    """Render a CAD file and export it as an SVG file

    Args:
        cat_file (str): Path to the CAD file
        output_filename (str): Path to the output PNG file
    """
    cad = cq.importers.importStep(os.fspath(cat_filepath))
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=True) as f:
        exporters.export(cad, f.name)
        drawing = svg2rlg(f.name)

    renderPM.drawToFile(drawing, os.fspath(output_filepath), fmt="PNG")
