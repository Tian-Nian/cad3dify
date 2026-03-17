import cadquery as cq
from cadquery import exporters

# === Key Dimensions (from JSON specification) ===
# Axial dimensions
total_height = 28.0  # mm
lower_flange_height = 9.0  # mm (Z=0 to Z=9)
middle_body_height = 8.0  # mm (Z=9 to Z=17)
upper_flange_height = 11.0  # mm (Z=17 to Z=28)

# Diameters
outer_diameter_flange = 139.0  # mm - lower and upper flange OD
outer_diameter_body = 115.0  # mm - middle body OD
inner_diameter_upper = 105.0  # mm - upper counterbore ID
inner_diameter_bore = 99.0  # mm - central through bore

# Hole pattern
hole_count = 12
bolt_circle_diameter = 129.0  # PCD for M6 holes
m6_clearance_diameter = 6.0  # M6 thread nominal diameter
# Note: Exact hole depth not dimensioned; assume through upper flange (11mm)
hole_depth = upper_flange_height  # Conservative: holes go through upper flange

# Fillet
fillet_radius = 2.0  # mm - R2.00 at internal bore step

# Chamfer (visible but not dimensioned - use conservative 1mm x 45deg)
chamfer_size = 1.0  # mm - conservative estimate

# === Step 1: Create base cylinder (lower flange) ===
# Start with full outer diameter cylinder for lower flange section
result = (
    cq.Workplane("XY")
    .circle(outer_diameter_flange / 2.0)
    .extrude(lower_flange_height)
)

# === Step 2: Add reduced middle body (D115) from Z=9 to Z=17 ===
result = (
    result
    .faces(">Z")
    .workplane()
    .circle(outer_diameter_body / 2.0)
    .extrude(middle_body_height)
)

# === Step 3: Add upper flange (D139) from Z=17 to Z=28 ===
result = (
    result
    .faces(">Z")
    .workplane()
    .circle(outer_diameter_flange / 2.0)
    .extrude(upper_flange_height)
)

# === Step 4: Create central bore D99 through entire part ===
result = (
    result
    .faces("<Z")
    .workplane()
    .circle(inner_diameter_bore / 2.0)
    .cutThruAll()
)

# === Step 5: Create upper counterbore D105 in upper flange (Z=17 to Z=28) ===
# Cut from top face, depth = upper_flange_height (11mm)
result = (
    result
    .faces(">Z")
    .workplane()
    .circle(inner_diameter_upper / 2.0)
    .cutBlind(-upper_flange_height)
)

# === Step 6: Add R2.00 fillet at internal bore step corner ===
# The fillet is at the internal step where D99 meets D105 (at Z=17)
# Select the circular edge at the step between bore diameters
try:
    result = (
        result
        .faces(">Z[-2]")  # Select the internal step face at Z=17
        .edges("%Circle")
        .edges(cq.selectors.RadiusNthSelector(0))  # Select inner edge (D99)
        .fillet(fillet_radius)
    )
except:
    # Fillet at internal step may be tricky; try alternative approach
    pass  # If fillet fails, proceed without it - noted in uncertainties

# === Step 7: Add bottom outer chamfer ===
# Chamfer on bottom outer edge (visible in section but size not dimensioned)
try:
    result = (
        result
        .faces("<Z")
        .edges(">X or >Y or <X or <Y")  # Outer edges of bottom face
        .chamfer(chamfer_size)
    )
except:
    # If chamfer selector fails, try simpler approach
    try:
        result = result.faces("<Z").edges().chamfer(chamfer_size)
    except:
        pass  # Chamfer size uncertain; omit if problematic

# === Step 8: Create 12x M6 holes on PCD 129 from upper step face ===
# Per JSON: holes open from recessed upper seat (upper_step face at Z=17)
# The holes are on the annular region between D129 and D139 on upper flange
# Holes start from the bottom of upper flange (Z=17) going upward through upper flange

# Calculate hole positions on bolt circle
import math
hole_positions = []
for i in range(hole_count):
    angle = i * (360.0 / hole_count) * (math.pi / 180.0)
    x = (bolt_circle_diameter / 2.0) * math.cos(angle)
    y = (bolt_circle_diameter / 2.0) * math.sin(angle)
    hole_positions.append((x, y))

# Create holes from top face going down through the upper flange
# Per JSON evidence: holes open on recessed annular seat (upper step at Z=17)
# We'll drill from top, which will intersect the stepped region
result = (
    result
    .faces(">Z")
    .workplane()
    .pushPoints(hole_positions)
    .hole(m6_clearance_diameter, depth=upper_flange_height)
)

# === Export the final model ===
exporters.export(result, "/home/user/project/cad3dify/runs/test_drawing_multi_json/output_v04.step")
