import cadquery as cq
from cadquery import exporters
import math

# =============================================================================
# Circular Flange with Bolt Hole Pattern
# Based on CAD Specification JSON
# =============================================================================

# Key dimensions (all in mm)
total_height = 28.0
lower_flange_height = 9.0
middle_body_height = 11.0
upper_rim_height = 8.0  # 28 - 20 = 8

outer_diameter_flange = 139.0
outer_diameter_body = 129.0
bolt_circle_diameter = 115.0
inner_diameter_upper = 105.0
inner_diameter_bore = 99.0

fillet_radius_inner = 2.0

# Bolt hole parameters
bolt_hole_count = 12
bolt_hole_diameter = 6.0  # M6 nominal diameter

# Derived radii
r_outer_flange = outer_diameter_flange / 2.0  # 69.5
r_outer_body = outer_diameter_body / 2.0       # 64.5
r_bolt_circle = bolt_circle_diameter / 2.0     # 57.5
r_inner_upper = inner_diameter_upper / 2.0     # 52.5
r_inner_bore = inner_diameter_bore / 2.0       # 49.5

# Z-levels from section analysis:
z_lower_flange_top = 9.0
z_middle_body_top = 20.0
z_top = 28.0

# =============================================================================
# Build the stepped profile for revolution with fillet arc included
# Profile is drawn in XZ plane (X = radius, Z = height)
# 
# Section bands analysis:
# - Lower flange: Z=0-9, OD=139, ID=99
# - Middle body: Z=9-20, OD=129, ID=99
# - Upper rim outer: Z=20-28, OD=139, ID=115 (solid ring)
# - Upper inner wall: Z=20-28, OD=105, ID=99 (solid ring)
# - Upper cavity: Z=20-28, OD=115, ID=105 (void)
# =============================================================================

fillet_r = fillet_radius_inner

# Build outer profile (counter-clockwise from origin going outward)
# The profile shows:
# - Bottom at Z=0: from bore (R=49.5) to flange OD (R=69.5)
# - Z=0 to Z=9: outer at R=69.5
# - Z=9: step inward to R=64.5
# - Z=9 to Z=20: outer at R=64.5
# - Z=20: step outward to R=69.5
# - Z=20 to Z=28: outer at R=69.5
# - Top at Z=28: from R=69.5 inward to upper opening

# Inner profile (bore with step):
# - Z=0 to Z=20: bore at R=49.5
# - Z=20: step outward to R=52.5 with R2 fillet
# - Z=20 to Z=28: inner wall at R=52.5

result = (
    cq.Workplane("XZ")
    .moveTo(r_inner_bore, 0)
    # Go right along bottom to outer flange
    .lineTo(r_outer_flange, 0)
    # Go up outer wall of lower flange
    .lineTo(r_outer_flange, z_lower_flange_top)
    # Step inward to body OD
    .lineTo(r_outer_body, z_lower_flange_top)
    # Go up middle body
    .lineTo(r_outer_body, z_middle_body_top)
    # Step outward back to flange OD for upper rim
    .lineTo(r_outer_flange, z_middle_body_top)
    # Go up to top
    .lineTo(r_outer_flange, z_top)
    # Go inward along top face to upper opening
    .lineTo(r_inner_upper, z_top)
    # Go down to internal floor level
    .lineTo(r_inner_upper, z_middle_body_top)
    # Go inward on floor, stopping short for fillet
    .lineTo(r_inner_bore + fillet_r, z_middle_body_top)
    # Arc (fillet) - 90 degree arc from floor to vertical wall
    .threePointArc(
        (r_inner_bore + fillet_r * (1 - math.cos(math.pi/4)), 
         z_middle_body_top + fillet_r * (1 - math.sin(math.pi/4))),
        (r_inner_bore, z_middle_body_top + fillet_r)
    )
    # Go down the bore wall to bottom
    .lineTo(r_inner_bore, 0)
    .close()
    .revolve(360, (0, 0, 0), (0, 1, 0))
)

# =============================================================================
# Cut the upper annular cavity (void between Ø105 and Ø115 from Z=20 to Z=28)
# This creates the void space in the upper region
# =============================================================================

result = (
    result
    .faces(">Z")
    .workplane()
    .circle(r_bolt_circle)  # Outer boundary = 57.5
    .circle(r_inner_upper)  # Inner boundary = 52.5
    .cutBlind(-upper_rim_height)  # Cut down 8mm from top
)

# =============================================================================
# Create 12x M6 bolt holes on PCD Ø115
# Per JSON: holes are in upper_flange layer, depth = upper_rim_height (8mm)
# The bolt holes are on the solid outer rim between Ø115 and Ø139
# =============================================================================

result = (
    result
    .faces(">Z")
    .workplane()
    .polarArray(r_bolt_circle, 0, 360, bolt_hole_count)
    .circle(bolt_hole_diameter / 2.0)
    .cutBlind(-upper_rim_height)  # Only through the upper flange layer (8mm)
)

# =============================================================================
# Export the result
# =============================================================================

exporters.export(result, "/home/user/project/cad3dify/runs/test_drawing_multi_json/output_v09.step")
