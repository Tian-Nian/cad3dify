import cadquery as cq
from cadquery import exporters


# Geometry reconstructed from the provided reference STEP, with user fixes:
# 1. bolt holes explicitly cut through to the bottom face
# 2. remove the extra rounded/chamfered transition between the top opening and the second level
outer_diameter = 139.0
upper_opening_diameter = 129.0
recess_floor_outer_diameter = 125.0
central_bore_diameter = 99.0
lower_bore_diameter = 105.0
bolt_circle_diameter = 115.0
bolt_hole_diameter = 6.0
bolt_hole_count = 12

total_height = 28.0
upper_opening_straight_depth = 9.0
recess_floor_z = 17.0
lower_bore_step_z = 9.0
bolt_hole_depth = recess_floor_z

outer_radius = outer_diameter / 2.0
upper_opening_radius = upper_opening_diameter / 2.0
recess_floor_outer_radius = recess_floor_outer_diameter / 2.0
central_bore_radius = central_bore_diameter / 2.0
lower_bore_radius = lower_bore_diameter / 2.0
bolt_circle_radius = bolt_circle_diameter / 2.0

top_z = total_height
upper_opening_bottom_z = total_height - upper_opening_straight_depth


# Right-half section profile in the XZ plane.
# The 129 -> 125 transition is modeled as a sharp step rather than a rounded/chamfered link.
result = (
    cq.Workplane("XZ")
    .moveTo(outer_radius, 0.0)
    .lineTo(outer_radius, top_z)
    .lineTo(upper_opening_radius, top_z)
    .lineTo(upper_opening_radius, upper_opening_bottom_z)
    .lineTo(recess_floor_outer_radius, upper_opening_bottom_z)
    .lineTo(recess_floor_outer_radius, recess_floor_z)
    .lineTo(central_bore_radius, recess_floor_z)
    .lineTo(central_bore_radius, lower_bore_step_z)
    .lineTo(lower_bore_radius, lower_bore_step_z)
    .lineTo(lower_bore_radius, 0.0)
    .close()
    .revolve(360, (0, 0, 0), (0, 1, 0))
)


# Cut the 12 bolt holes from the recessed floor all the way to the bottom.
holes = (
    cq.Workplane("XY", origin=(0, 0, recess_floor_z))
    .polarArray(bolt_circle_radius, 0, 360, bolt_hole_count)
    .circle(bolt_hole_diameter / 2.0)
    .extrude(-bolt_hole_depth)
)

result = result.cut(holes)


exporters.export(result, "/home/user/project/cad3dify/runs/test_drawing_multi_json/output_v06.step")