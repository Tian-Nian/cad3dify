import cadquery as cq
from cadquery import exporters

# ============================================
# Flanged Ring with Bolt Holes
# ============================================
# A circular flanged component with a central bore, 
# stepped profile, and 12 equally spaced M6 threaded holes

# Key dimensions (all in mm)
outer_diameter = 139.0
outer_radius = outer_diameter / 2.0

outer_step_diameter = 129.0
outer_step_radius = outer_step_diameter / 2.0

bolt_circle_diameter = 115.0
bolt_circle_radius = bolt_circle_diameter / 2.0

inner_step_diameter = 105.0
inner_step_radius = inner_step_diameter / 2.0

central_bore_diameter = 99.0
central_bore_radius = central_bore_diameter / 2.0

total_height = 28.0
upper_section_height = 17.0  # Height where inner step starts from bottom
lower_flange_height = 11.0   # Height of counterbore step from top
bottom_step_height = 9.0     # Height of outer step recess from bottom

fillet_radius = 2.0

# M6 hole parameters
m6_hole_diameter = 6.0  # Nominal M6 diameter (for clearance/threaded hole)
num_holes = 12
angle_step = 360.0 / num_holes  # 30 degrees

# Conservative assumption: M6 holes are through holes based on uncertainty
m6_hole_depth = total_height  # Through hole

# ============================================
# Step 1: Create base cylindrical body
# ============================================
result = (
    cq.Workplane("XY")
    .circle(outer_radius)
    .extrude(total_height)
)

# ============================================
# Step 2: Cut central through bore Ø99mm
# ============================================
result = (
    result
    .faces(">Z")
    .workplane()
    .hole(central_bore_diameter, total_height)
)

# ============================================
# Step 3: Cut counterbore step Ø105mm from top
# Depth 11mm (lower_flange_height)
# ============================================
result = (
    result
    .faces(">Z")
    .workplane()
    .circle(inner_step_radius)
    .cutBlind(-lower_flange_height)
)

# ============================================
# Step 4: Cut outer annular recess at Ø129mm from bottom
# Height 9mm from bottom, leaving flange at full OD above
# ============================================
# This creates a step where OD goes from 129mm to 139mm at height 9mm
result = (
    result
    .faces("<Z")
    .workplane()
    .circle(outer_radius)
    .circle(outer_step_radius)
    .cutBlind(bottom_step_height)
)

# ============================================
# Step 5: Add R2mm fillet at internal step transition
# The internal step is where Ø99 meets Ø105 at height 17mm from bottom
# ============================================
# Select the circular edge at the transition between bore and counterbore
result = (
    result
    .faces(">Z")
    .workplane(offset=-lower_flange_height)
    .edges("%Circle")
    .edges(cq.selectors.RadiusNthSelector(0))  # Select inner edge
)

# Alternative approach: select by filtering edges near the step
# Due to complexity, apply fillet to the inner step edge
try:
    result = (
        cq.Workplane("XY")
        .circle(outer_radius)
        .extrude(total_height)
    )
    
    # Cut central through bore
    result = (
        result
        .faces(">Z")
        .workplane()
        .hole(central_bore_diameter, total_height)
    )
    
    # Cut counterbore step from top
    result = (
        result
        .faces(">Z")
        .workplane()
        .circle(inner_step_radius)
        .cutBlind(-lower_flange_height)
    )
    
    # Cut outer annular recess from bottom
    result = (
        result
        .faces("<Z")
        .workplane()
        .circle(outer_radius)
        .circle(outer_step_radius)
        .cutBlind(bottom_step_height)
    )
    
    # Apply fillet to the internal step corner
    # Select edge at the step between Ø99 and Ø105
    result = (
        result
        .edges(
            cq.selectors.AndSelector(
                cq.selectors.RadiusNthSelector(1),  # Second smallest radius edge
                cq.selectors.DirectionMinMaxSelector(cq.Vector(0, 0, 1), directionMax=False)
            )
        )
    )
except:
    pass

# Rebuild model with simpler fillet approach
result = (
    cq.Workplane("XY")
    .circle(outer_radius)
    .extrude(total_height)
)

# Cut central through bore
result = (
    result
    .faces(">Z")
    .workplane()
    .hole(central_bore_diameter, total_height)
)

# Cut counterbore step from top
result = (
    result
    .faces(">Z")
    .workplane()
    .circle(inner_step_radius)
    .cutBlind(-lower_flange_height)
)

# Cut outer annular recess from bottom
result = (
    result
    .faces("<Z")
    .workplane()
    .circle(outer_radius)
    .circle(outer_step_radius)
    .cutBlind(bottom_step_height)
)

# Apply R2 fillet to the internal step edge (where bore meets counterbore)
# This edge is a horizontal circle at Z = total_height - lower_flange_height = 17mm
# with radius equal to central_bore_radius
step_z_height = total_height - lower_flange_height

result = (
    result
    .edges(
        cq.selectors.NearestToPointSelector((central_bore_radius, 0, step_z_height))
    )
    .fillet(fillet_radius)
)

# ============================================
# Step 6: Create 12x M6 holes on PCD Ø115mm
# Angular spacing of 30 degrees
# Conservative: through holes since depth not specified
# ============================================
result = (
    result
    .faces(">Z")
    .workplane()
    .polarArray(bolt_circle_radius, 0, 360, num_holes)
    .hole(m6_hole_diameter, total_height)
)

# ============================================
# Verify model validity
# ============================================
if result.val().isValid():
    print("Model is valid")
else:
    print("Warning: Model may have issues")

# ============================================
# Export to STEP file
# ============================================
exporters.export(result, "/home/user/project/cad3dify/runs/test_full_chain/output_v01.step")
