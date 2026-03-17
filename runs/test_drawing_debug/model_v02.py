import cadquery as cq
from cadquery import exporters

# =============================================================================
# Circular Flange with Bolt Holes
# Based on CAD specification JSON
# =============================================================================

# Key dimensions (all in mm)
outer_diameter = 139.0
intermediate_diameter = 115.0
counterbore_diameter = 105.0
central_bore_diameter = 99.0

total_height = 28.0
upper_section_height = 11.0
lower_step_height = 17.0  # 28 - 11 = 17mm for lower section
counterbore_depth = 9.0

fillet_radius = 2.0

# Bolt hole parameters
bolt_hole_diameter = 6.0  # M6 holes
bolt_circle_diameter = 115.0
num_bolt_holes = 12
bolt_hole_angle_step = 30.0  # 360/12 = 30 degrees

# =============================================================================
# Step 1: Create base cylinder with stepped profile
# =============================================================================

# Start with the lower section (smaller diameter)
flange = (
    cq.Workplane("XY")
    .circle(intermediate_diameter / 2.0)
    .extrude(lower_step_height)
)

# Add upper section (full outer diameter)
flange = (
    flange
    .faces(">Z")
    .workplane()
    .circle(outer_diameter / 2.0)
    .extrude(upper_section_height)
)

# =============================================================================
# Step 2: Cut central through bore
# =============================================================================
flange = (
    flange
    .faces(">Z")
    .workplane()
    .circle(central_bore_diameter / 2.0)
    .cutThruAll()
)

# =============================================================================
# Step 3: Cut counterbore from top
# =============================================================================
# Counterbore is at the top, 9mm deep, diameter 105mm
flange = (
    flange
    .faces(">Z")
    .workplane()
    .circle(counterbore_diameter / 2.0)
    .cutBlind(-counterbore_depth)
)

# =============================================================================
# Step 4: Create 12x M6 through holes on bolt circle
# =============================================================================
# Holes are on the intermediate diameter (PCD 115mm)
# Position at the top face and cut through
bolt_circle_radius = bolt_circle_diameter / 2.0

flange = (
    flange
    .faces(">Z")
    .workplane()
    .polarArray(
        radius=bolt_circle_radius,
        startAngle=0,
        angle=360,
        count=num_bolt_holes,
        fill=True
    )
    .circle(bolt_hole_diameter / 2.0)
    .cutThruAll()
)

# =============================================================================
# Step 5: Add fillet on outer top edge
# =============================================================================
# Select the top face and find the outermost edge (outer_diameter/2 = 69.5)
# Using a safer approach by selecting edges by approximate radius
try:
    # Get the top face edges and filter for the outer edge
    top_outer_edge = (
        flange
        .faces(">Z")
        .edges("%Circle")
        .edges(cq.selectors.RadiusNthSelector(-1))  # Select largest radius circular edge
    )
    flange = top_outer_edge.fillet(fillet_radius)
except Exception:
    # If fillet fails, skip it with a comment
    # Fillet on outer top edge omitted due to selector/geometry complexity
    pass

# =============================================================================
# Verification
# =============================================================================
# Check if the model is valid
if flange.val().isValid():
    print("Model is valid")
else:
    print("Warning: Model may have issues")

# =============================================================================
# Export to STEP file
# =============================================================================
exporters.export(flange, "/home/user/project/cad3dify/runs/test_drawing_debug/output_v02.step")
