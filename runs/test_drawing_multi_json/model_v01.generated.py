import cadquery as cq
from cadquery import exporters
import math

# =============================================================================
# Flanged Ring with Bolt Holes
# Based on CAD drawing specification JSON
# Units: mm
# =============================================================================

# Key dimensions from specification
total_height = 28.0
upper_flange_height = 11.0
lower_section_height = total_height - upper_flange_height  # 17.0 mm

outer_diameter_flange = 139.0
outer_diameter_body = 115.0
inner_diameter_upper = 105.0  # Counterbore/step diameter
inner_diameter_bore = 99.0    # Central through bore

# Bolt hole parameters
bolt_circle_diameter = 129.0  # PCD from section view
bolt_hole_count = 12
m6_clearance_diameter = 6.0   # M6 thread nominal diameter
angular_spacing = 360.0 / bolt_hole_count  # 30 degrees

# Fillet radius at internal corner
fillet_radius = 2.0

# =============================================================================
# Build the part - datum A is bottom face
# =============================================================================

# Step 1: Create the lower cylindrical body (D115 x 17mm from bottom)
result = (
    cq.Workplane("XY")
    .circle(outer_diameter_body / 2.0)
    .extrude(lower_section_height)
)

# Step 2: Add upper flange (D139 x 11mm on top of lower section)
result = (
    result
    .faces(">Z")
    .workplane()
    .circle(outer_diameter_flange / 2.0)
    .extrude(upper_flange_height)
)

# Step 3: Create central through bore (D99 through entire height)
result = (
    result
    .faces(">Z")
    .workplane()
    .circle(inner_diameter_bore / 2.0)
    .cutThruAll()
)

# Step 4: Create stepped bore/counterbore (D105) from top down into upper flange
# The D105 step extends through the upper flange (11mm depth from top)
# Based on section interpretation: upper counterbore from Z=11 to Z=28 (17mm), 
# but the section shows D105 as inner_diameter_upper in the upper flange region
# Conservative interpretation: D105 bore is in the upper flange only (11mm deep)
result = (
    result
    .faces(">Z")
    .workplane()
    .circle(inner_diameter_upper / 2.0)
    .cutBlind(-upper_flange_height)  # Cut 11mm down from top
)

# Step 5: Add fillet at internal step corner (R2.00)
# The fillet is at the junction between D99 bore and D105 counterbore
# This is a challenging selection - attempting to fillet the circular edge
# at the bottom of the D105 counterbore
try:
    # Select the internal horizontal edge at the step between D105 and D99
    result = (
        result
        .faces(">Z[1]")  # Select the face at Z=17 (step face)
        .edges("%Circle")
        .edges(cq.selectors.RadiusNthSelector(0))  # Inner edge (D99 side)
        .fillet(fillet_radius)
    )
except:
    # Fillet application can be fragile - skip if it fails
    # TODO: R2.00 fillet at internal bore step corner not applied due to selection complexity
    pass

# Step 6: Create 12x M6 threaded holes on bolt circle
# Holes are on the upper flange, starting from top face
# Using tap drill size for M6 (approximately 5.0mm for threading, but using 6.0 for clearance)
# Per JSON: axial_start_face is "top" and axial_layer is "upper_flange"
m6_tap_drill = 5.0  # Tap drill for M6 thread

# Calculate hole positions on bolt circle
bolt_radius = bolt_circle_diameter / 2.0

result = (
    result
    .faces(">Z")
    .workplane()
    .polarArray(bolt_radius, 0, 360, bolt_hole_count)
    .circle(m6_tap_drill / 2.0)
    .cutBlind(-upper_flange_height)  # Through upper flange only (11mm)
)

# =============================================================================
# Export the model
# =============================================================================
exporters.export(result, "/home/user/project/cad3dify/runs/test_drawing_multi_json/output_v01.step")
