import cadquery as cq
from cadquery import exporters


# Geometry reconstructed from the provided reference STEP.
outer_diameter = 139.0
upper_opening_diameter = 129.0
recess_floor_outer_diameter = 125.0
central_bore_diameter = 99.0
lower_bore_diameter = 105.0
bolt_circle_diameter = 115.0
bolt_hole_diameter = 6.0
bolt_hole_count = 12
transition_radius = 2.0

total_height = 28.0
upper_opening_straight_depth = 9.0
transition_depth = 2.0
recess_floor_z = 17.0
lower_bore_step_z = 9.0
bolt_hole_depth = 17.0

outer_radius = outer_diameter / 2.0
upper_opening_radius = upper_opening_diameter / 2.0
recess_floor_outer_radius = recess_floor_outer_diameter / 2.0
central_bore_radius = central_bore_diameter / 2.0
lower_bore_radius = lower_bore_diameter / 2.0
bolt_circle_radius = bolt_circle_diameter / 2.0

top_z = total_height
upper_opening_bottom_z = total_height - upper_opening_straight_depth


# Right-half section profile in the XZ sketch plane.
result = (
    cq.Workplane("XZ")
    .moveTo(outer_radius, 0.0)
    .lineTo(outer_radius, top_z)
    .lineTo(upper_opening_radius, top_z)
    .lineTo(upper_opening_radius, upper_opening_bottom_z)
    .radiusArc((recess_floor_outer_radius, recess_floor_z), -transition_radius)
    .lineTo(central_bore_radius, recess_floor_z)
    .lineTo(central_bore_radius, lower_bore_step_z)
    .lineTo(lower_bore_radius, lower_bore_step_z)
    .lineTo(lower_bore_radius, 0.0)
    .close()
    .revolve(360, (0, 0, 0), (0, 1, 0))
)


# Holes start from the recessed annular floor and run down to the bottom face.
result = (
    result
    .faces(">Z[1]")
    .workplane()
    .polarArray(bolt_circle_radius, 0, 360, bolt_hole_count)
    .hole(bolt_hole_diameter, depth=bolt_hole_depth)
)


exporters.export(result, "/home/user/project/cad3dify/runs/test_drawing_multi_json/output_v05.step")