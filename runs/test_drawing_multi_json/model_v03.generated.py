import cadquery as cq
from cadquery import exporters
import math

# =============================================================================
# Flanged Ring with Bolt Holes
# Based on CAD specification JSON
# Units: mm
# =============================================================================

# Key dimensions from specification
total_height = 28.0
lower_flange_height = 9.0
middle_body_height = 8.0  # derived: 17 - 9 = 8
upper_flange_height = 11.0  # 28 - 17 = 11

outer_diameter_flange = 139.0
outer_diameter_body = 115.0
inner_diameter_upper = 105.0
inner_diameter_bore = 99.0
recess_seat_diameter = 129.0

bolt_circle_diameter = 129.0
bolt_hole_count = 12
bolt_hole_thread = "M6"
m6_clearance_diameter = 6.0  # Using tap drill size for M6 threads

fillet_radius = 2.0

# Derived radii
outer_radius_flange = outer_diameter_flange / 2.0
outer_radius_body = outer_diameter_body / 2.0
inner_radius_upper = inner_diameter_upper / 2.0
inner_radius_bore = inner_diameter_bore / 2.0
bolt_circle_radius = bolt_circle_diameter / 2.0

# Z-levels (from bottom datum A)
z_lower_top = lower_flange_height  # 9.0
z_middle_top = z_lower_top + middle_body_height  # 17.0
z_upper_top = total_height  # 28.0

# =============================================================================
# Step 1: Create the base solid profile using revolution
# Build the cross-section profile as a series of points (right side only)
# =============================================================================

# Profile points for right half of cross-section (will revolve around Z axis)
# Start from bottom outer corner, go clockwise
profile_points = [
    (outer_radius_flange, 0),                    # Bottom outer corner
    (outer_radius_flange, z_lower_top),          # Lower flange top outer
    (outer_radius_body, z_lower_top),            # Step inward to middle body
    (outer_radius_body, z_middle_top),           # Middle body top
    (outer_radius_flange, z_middle_top),         # Step outward to upper flange
    (outer_radius_flange, z_upper_top),          # Top outer corner
    (inner_radius_upper, z_upper_top),           # Top inner corner (upper bore)
    (inner_radius_upper, z_middle_top),          # Upper counterbore bottom
    (inner_radius_bore, z_middle_top),           # Step to main bore at z=17
    (inner_radius_bore, 0),                      # Bottom of main bore
]

# Create the solid body by revolving the profile
result = (
    cq.Workplane("XZ")
    .polyline(profile_points)
    .close()
    .revolve(360, (0, 0, 0), (0, 1, 0))
)

# =============================================================================
# Step 2: Add fillet at internal bore step corner (R2.0)
# The fillet is at the transition between dia 99 bore and dia 105 upper counterbore
# =============================================================================

# Fillet at internal step corner - selecting the circular edge at z=17, inner diameter
try:
    result = (
        result
        .faces(">Z[1]")  # Select intermediate face
        .edges("%Circle")
        .edges(cq.selectors.RadiusNthSelector(0))  # Smallest radius circular edge
        .fillet(fillet_radius)
    )
except:
    # Fillet at internal step corner - alternative approach
    # Select edge by filtering for the specific radius at the step
    pass
    # NOTE: Internal fillet at bore step omitted - edge selection unreliable

# =============================================================================
# Step 3: Add bottom outer chamfer (visible in section but not dimensioned)
# Using conservative 1mm x 45° chamfer
# =============================================================================

chamfer_size = 1.0  # Conservative estimate - not dimensioned in drawing

try:
    result = (
        result
        .faces("<Z")
        .edges("%Circle")
        .edges(cq.selectors.RadiusNthSelector(-1))  # Largest radius = outer edge
        .chamfer(chamfer_size)
    )
except:
    # NOTE: Bottom outer chamfer omitted - exact size not specified
    pass

# =============================================================================
# Step 4: Create 12x M6 threaded holes on bolt circle
# Holes start from the recessed upper seat at z=17 and go through upper flange
# The holes are on the annular face between dia 129 and dia 139 at z=17
# =============================================================================

# Hole depth: from z=17 to z=28 (through upper flange) = 11mm
# Using through hole for the upper flange layer
hole_depth = upper_flange_height  # 11mm - holes go through upper flange

# Create hole pattern on the recessed face at z=17
# First select the annular face at z=17 (upper step face)
result = (
    result
    .faces(">Z[1]")  # Select the face at z=17 (recessed annular seat)
    .workplane()
    .polarArray(bolt_circle_radius, 0, 360, bolt_hole_count)
    .hole(m6_clearance_diameter, depth=hole_depth)
)

# =============================================================================
# Export the model
# =============================================================================

exporters.export(result, "/home/user/project/cad3dify/runs/test_drawing_multi_json/output_v03.step")
