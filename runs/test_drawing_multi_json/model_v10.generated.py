import cadquery as cq
from cadquery import exporters
import math

# =============================================================================
# Circular Transition Flange with Recessed Hole Seat
# =============================================================================

# Overall dimensions
total_height = 28.0  # mm
outer_diameter = 139.0  # mm

# Upper opening dimensions
upper_opening_diameter = 129.0  # mm
upper_opening_straight_depth = 9.0  # mm - from Z=28 to Z=19

# Recessed seat dimensions
recess_seat_diameter = 125.0  # mm
recess_floor_z = 17.0  # mm

# Fillet transition
fillet_radius = 2.0  # mm - R2 transition

# Central bore dimensions
upper_bore_diameter = 99.0  # mm - from Z=17 to Z=9
lower_bore_diameter = 105.0  # mm - from Z=9 to Z=0
lower_bore_step_z = 9.0  # mm

# Hole pattern
hole_count = 12
hole_diameter = 6.0  # mm
bolt_circle_diameter = 115.0  # mm - PCD

# Derived radii
outer_radius = outer_diameter / 2.0  # 69.5
upper_opening_radius = upper_opening_diameter / 2.0  # 64.5
recess_seat_radius = recess_seat_diameter / 2.0  # 62.5
upper_bore_radius = upper_bore_diameter / 2.0  # 49.5
lower_bore_radius = lower_bore_diameter / 2.0  # 52.5

# Z levels
z_top = total_height  # 28.0
z_fillet_top = z_top - upper_opening_straight_depth  # 19.0
z_recess_floor = recess_floor_z  # 17.0
z_bore_step = lower_bore_step_z  # 9.0
z_bottom = 0.0

# =============================================================================
# Build the axisymmetric body using a revolved profile in XZ plane
# X = radius, Z = height, revolve around Z axis
# =============================================================================

# R2 fillet arc parameters
# Arc connects: (recess_seat_radius, z_recess_floor) to (upper_opening_radius, z_fillet_top)
# Arc center at (recess_seat_radius + R, z_recess_floor + R) = (64.5, 19.0)
arc_center_x = recess_seat_radius + fillet_radius  # 64.5
arc_center_z = z_recess_floor + fillet_radius  # 19.0

# Arc start: (62.5, 17.0) - on the floor
arc_start_x = recess_seat_radius
arc_start_z = z_recess_floor

# Arc end: (64.5, 19.0) - on the vertical wall
arc_end_x = upper_opening_radius
arc_end_z = z_fillet_top

# Arc midpoint at 45 degrees
arc_mid_x = arc_center_x - fillet_radius * math.cos(math.pi/4)  # 64.5 - 1.414 = 63.086
arc_mid_z = arc_center_z - fillet_radius * math.sin(math.pi/4)  # 19.0 - 1.414 = 17.586

# Build the profile - trace the cross-section outline
# Starting from inner bottom and going clockwise around the solid material
profile = (
    cq.Workplane("XZ")
    .moveTo(lower_bore_radius, z_bottom)  # Start at inner bottom R=52.5, Z=0
    .lineTo(lower_bore_radius, z_bore_step)  # Up lower bore wall to Z=9
    .lineTo(upper_bore_radius, z_bore_step)  # Step inward to R=49.5 at Z=9
    .lineTo(upper_bore_radius, z_recess_floor)  # Up upper bore wall to Z=17
    .lineTo(arc_start_x, arc_start_z)  # Across recessed floor to R=62.5, Z=17
    .threePointArc((arc_mid_x, arc_mid_z), (arc_end_x, arc_end_z))  # R2 fillet arc
    .lineTo(upper_opening_radius, z_top)  # Up opening wall to R=64.5, Z=28
    .lineTo(outer_radius, z_top)  # Across top face to R=69.5, Z=28
    .lineTo(outer_radius, z_bottom)  # Down outer wall to R=69.5, Z=0
    .lineTo(lower_bore_radius, z_bottom)  # Across bottom face back to start
    .close()
)

# Revolve around Z axis (which is Y in XZ workplane)
body = profile.revolve(360, (0, 0, 0), (0, 1, 0))

# =============================================================================
# Add 12-hole pattern on the recessed seat at Z=17
# Holes cut from Z=17 down to Z=0 (depth = 17mm)
# =============================================================================

pcd_radius = bolt_circle_diameter / 2.0  # 57.5 mm

# Calculate hole center positions
hole_positions = []
for i in range(hole_count):
    angle_rad = i * (2 * math.pi / hole_count)
    x = pcd_radius * math.cos(angle_rad)
    y = pcd_radius * math.sin(angle_rad)
    hole_positions.append((x, y))

# Create a workplane at Z=17 (the recessed seat level) and cut holes downward
# The holes should start at the recessed annular face which is at Z=17
result = (
    body
    .faces(">Z[1]")  # Select the recessed seat face (second highest Z face)
    .workplane()
    .pushPoints(hole_positions)
    .hole(hole_diameter, depth=z_recess_floor)  # Cut 17mm deep to reach bottom
)

# =============================================================================
# Export the final model
# =============================================================================
exporters.export(result, "/home/user/project/cad3dify/runs/test_drawing_multi_json/output_v10.step")
