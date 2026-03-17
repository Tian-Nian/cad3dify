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

# ============================================
# Build the part using a revolved profile approach
# This creates the stepped profile more reliably
# ============================================

# Define the cross-section profile points (r, z) from bottom to top
# Starting at inner bore bottom, going clockwise around the profile
# Profile is on the right side of the revolution axis (positive X)

# The profile in XZ plane (X = radius, Z = height)
# Points define the outer boundary of the solid cross-section

profile_points = [
    # Start at bore, bottom
    (central_bore_radius, 0),
    # Go to outer step radius at bottom
    (outer_step_radius, 0),
    # Go up to outer step height
    (outer_step_radius, bottom_step_height),
    # Step out to full outer radius
    (outer_radius, bottom_step_height),
    # Go up to top
    (outer_radius, total_height),
    # Go in to inner step radius at top
    (inner_step_radius, total_height),
    # Go down to inner step depth (11mm from top = 17mm from bottom)
    (inner_step_radius, upper_section_height),
    # Step in to bore radius
    (central_bore_radius, upper_section_height),
    # Close back to start (bore at bottom)
    (central_bore_radius, 0),
]

# Create the profile and revolve it
result = (
    cq.Workplane("XZ")
    .polyline(profile_points)
    .close()
    .revolve(360, (0, 0, 0), (0, 1, 0))
)

# ============================================
# Add R2mm fillet at internal step transition
# The step is at z=17mm between Ø99 and Ø105
# ============================================
# Select edges near the internal step corner
try:
    # Find edges at the step transition
    result = (
        result
        .edges("|Z")  # Select vertical edges
        .edges(cq.selectors.RadiusNthSelector(1))  # Try to select by radius
    )
    # If selection worked, apply fillet - but this approach is fragile
    # Skip fillet if it causes issues
except:
    pass

# Safer approach: select edges by location
try:
    step_z = upper_section_height  # z = 17mm
    # Select the horizontal circular edge at the step
    result_with_fillet = (
        result
        .edges(cq.selectors.NearestToPointSelector((inner_step_radius, 0, step_z)))
        .fillet(fillet_radius)
    )
    result = result_with_fillet
except Exception as e:
    # Fillet failed - omit it and continue with the model
    print(f"Fillet omitted due to: {e}")

# ============================================
# Create 12x M6 holes on PCD Ø115mm
# Angular spacing of 30 degrees
# Through holes since depth not specified
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
exporters.export(result, "/home/user/project/cad3dify/runs/test_full_chain/output_v03.step")
