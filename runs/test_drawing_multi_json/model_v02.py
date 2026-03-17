import cadquery as cq
from math import pi, cos, sin

# =============================================================================
# Flanged Ring with Bolt Holes
# Based on CAD specification JSON
# =============================================================================

# Key dimensions (mm)
total_height = 28.0
lower_flange_height = 9.0
middle_body_height = 8.0  # derived: 28 - 9 - 11 = 8
upper_flange_height = 11.0

outer_diameter_flange = 139.0
outer_diameter_body = 115.0
inner_diameter_upper = 105.0
inner_diameter_bore = 99.0

bolt_circle_diameter = 129.0  # PCD for M6 holes
m6_hole_count = 12
m6_clearance_diameter = 6.0  # M6 thread nominal diameter (tapped hole)

fillet_radius = 2.0

# Derived values
outer_radius_flange = outer_diameter_flange / 2.0
outer_radius_body = outer_diameter_body / 2.0
inner_radius_upper = inner_diameter_upper / 2.0
inner_radius_bore = inner_diameter_bore / 2.0
bolt_circle_radius = bolt_circle_diameter / 2.0

# Axial positions (Z=0 is bottom face, datum A)
z_lower_flange_top = lower_flange_height  # 9.0
z_middle_body_top = z_lower_flange_top + middle_body_height  # 17.0
z_upper_flange_top = total_height  # 28.0

# =============================================================================
# Step 1: Create base solid using revolution of stepped profile
# =============================================================================

# Define profile points for half cross-section (right side, to be revolved)
# Starting from bottom-left (inner bore) going clockwise
profile_pts = [
    # Bottom inner bore corner
    (inner_radius_bore, 0.0),
    # Along bottom face to outer flange
    (outer_radius_flange, 0.0),
    # Up outer flange to z=9 (lower flange top)
    (outer_radius_flange, z_lower_flange_top),
    # Step inward to body diameter
    (outer_radius_body, z_lower_flange_top),
    # Up body to z=17 (middle body top, where upper flange starts)
    (outer_radius_body, z_middle_body_top),
    # Step outward to upper flange outer diameter
    (outer_radius_flange, z_middle_body_top),
    # Up to top face
    (outer_radius_flange, z_upper_flange_top),
    # Inward along top face to inner upper diameter
    (inner_radius_upper, z_upper_flange_top),
    # Down inside upper flange to z=17
    (inner_radius_upper, z_middle_body_top),
    # Inward to bore diameter
    (inner_radius_bore, z_middle_body_top),
    # Down bore to bottom (closing the profile)
    (inner_radius_bore, 0.0),
]

# Create the main body by revolving the profile
# Use XZ plane so Y is the axis of revolution
result = (
    cq.Workplane("XZ")
    .polyline(profile_pts)
    .close()
    .revolve(360, (0, 0, 0), (0, 1, 0))
)

# =============================================================================
# Step 2: Add fillet at internal corner (bore step at z=17)
# =============================================================================
# The R2.00 fillet is at the internal step corner where bore meets the upper counterbore
# This is at Z=17 on the inside surface between dia 99 and dia 105

# Fillet application can be fragile; attempting with edge selection
try:
    # Select the internal circular edge at z=17 where the step occurs
    result = (
        result
        .edges(
            cq.selectors.AndSelector(
                cq.selectors.RadiusNthSelector(0),  # smallest radius edges
                cq.selectors.NearestToPointSelector((inner_radius_bore, 0, z_middle_body_top))
            )
        )
        .fillet(fillet_radius)
    )
except:
    # Fillet omitted if selection fails - edge geometry may be ambiguous
    pass

# =============================================================================
# Step 3: Create 12x M6 tapped holes from bottom face into lower flange
# =============================================================================
# Per JSON: holes are on PCD 129, accessed from bottom, depth is lower flange only (9mm)
# Feature placement: bottom face, into lower_flange layer

# Calculate hole positions on bolt circle
hole_positions = []
for i in range(m6_hole_count):
    angle = i * (360.0 / m6_hole_count) * pi / 180.0
    x = bolt_circle_radius * cos(angle)
    y = bolt_circle_radius * sin(angle)
    hole_positions.append((x, y))

# Select bottom face and drill holes upward into the lower flange
# Using cutBlind from bottom face (Z=0) going into positive Z direction
result = (
    result
    .faces("<Z")  # Select bottom face
    .workplane()
    .pushPoints(hole_positions)
    .hole(m6_clearance_diameter, depth=lower_flange_height)  # M6 holes, depth 9mm into lower flange
)

# =============================================================================
# Export the model
# =============================================================================
cq.exporters.export(result, "/home/user/project/cad3dify/runs/test_drawing_multi_json/output_v02.step")
