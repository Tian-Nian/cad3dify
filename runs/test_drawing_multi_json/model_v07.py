import cadquery as cq
from cadquery import exporters
from math import sqrt


# Geometry reconstructed from the provided reference STEP, with user fixes:
# 1. bolt holes explicitly cut through to the bottom face
# 2. preserve the R2 transition shown in section view between the upper opening edge and the second level
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
transition_fillet_radius = 2.0

outer_radius = outer_diameter / 2.0
upper_opening_radius = upper_opening_diameter / 2.0
recess_floor_outer_radius = recess_floor_outer_diameter / 2.0
central_bore_radius = central_bore_diameter / 2.0
lower_bore_radius = lower_bore_diameter / 2.0
bolt_circle_radius = bolt_circle_diameter / 2.0

top_z = total_height
upper_opening_bottom_z = total_height - upper_opening_straight_depth


# Tangency midpoint for the R2 quarter-arc between the upper opening wall
# and the recessed second-level floor in the XZ profile.
fillet_mid_radius = upper_opening_radius - transition_fillet_radius / sqrt(2.0)
fillet_mid_z = recess_floor_z + transition_fillet_radius / sqrt(2.0)


result = (
    cq.Workplane("XZ")
    .moveTo(outer_radius, 0.0)
    .lineTo(outer_radius, top_z)
    .lineTo(upper_opening_radius, top_z)
    .lineTo(upper_opening_radius, upper_opening_bottom_z)
    .threePointArc(
        (fillet_mid_radius, fillet_mid_z),
        (recess_floor_outer_radius, recess_floor_z),
    )
    .lineTo(central_bore_radius, recess_floor_z)
    .lineTo(central_bore_radius, lower_bore_step_z)
    .lineTo(lower_bore_radius, lower_bore_step_z)
    .lineTo(lower_bore_radius, 0.0)
    .close()
    .revolve(360, (0, 0, 0), (0, 1, 0))
)


holes = (
    cq.Workplane("XY", origin=(0, 0, recess_floor_z))
    .polarArray(bolt_circle_radius, 0, 360, bolt_hole_count)
    .circle(bolt_hole_diameter / 2.0)
    .extrude(-bolt_hole_depth)
)

result = result.cut(holes)


exporters.export(result, "/home/user/project/cad3dify/runs/test_drawing_multi_json/output_v07.step")