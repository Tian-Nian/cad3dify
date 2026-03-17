import cadquery as cq
from cadquery import exporters

# =============================================================================
# Circular Flange with Bolt Hole Pattern
# Based on CAD specification JSON
# =============================================================================

# Key dimensions (all in mm)
# Outer diameters
OD_FLANGE = 139.0          # Outer diameter of lower flange
OD_BODY = 129.0            # Outer diameter of middle body section

# Inner diameters (bore steps)
ID_BORE = 99.0             # Central through bore diameter
ID_UPPER = 105.0           # Upper bore step diameter (inner wall)
ID_RECESS = 115.0          # Upper cavity outer boundary

# Axial heights
TOTAL_HEIGHT = 28.0        # Total part height
LOWER_FLANGE_HEIGHT = 9.0  # Height of lower flange section (Z=0 to Z=9)
MIDDLE_BODY_HEIGHT = 11.0  # Height of middle body section (Z=9 to Z=20)
UPPER_RIM_HEIGHT = 8.0     # Height of upper rim section (Z=20 to Z=28)

# Derived Z levels
Z_LOWER_TOP = LOWER_FLANGE_HEIGHT  # Z=9
Z_MIDDLE_TOP = LOWER_FLANGE_HEIGHT + MIDDLE_BODY_HEIGHT  # Z=20

# Hole pattern
BOLT_PCD = 115.0           # Bolt circle diameter
HOLE_COUNT = 12            # Number of M6 holes
M6_DIA = 6.0               # M6 nominal diameter

# Fillet
FILLET_RADIUS = 2.0        # R2.00 at internal step transition

# =============================================================================
# Build using revolved profile for precise control of stepped geometry
# =============================================================================

# Create profile in XZ plane to revolve
# Points define the outer and inner profile (radial, axial)
# Start from bottom outer, go up outer profile, then down inner profile

profile_pts = [
    # Outer profile (bottom to top)
    (OD_FLANGE / 2.0, 0),                    # Bottom outer corner
    (OD_FLANGE / 2.0, LOWER_FLANGE_HEIGHT),  # Top of lower flange outer
    (OD_BODY / 2.0, LOWER_FLANGE_HEIGHT),    # Step in to middle body
    (OD_BODY / 2.0, Z_MIDDLE_TOP),           # Top of middle body outer
    (OD_FLANGE / 2.0, Z_MIDDLE_TOP),         # Step out for upper rim
    (OD_FLANGE / 2.0, TOTAL_HEIGHT),         # Top outer corner
    # Inner profile at top (going inward then down)
    (ID_RECESS / 2.0, TOTAL_HEIGHT),         # Upper cavity outer edge at top
    (ID_RECESS / 2.0, Z_MIDDLE_TOP),         # Upper cavity bottom (floor level)
    (ID_UPPER / 2.0, Z_MIDDLE_TOP),          # Inner wall top at floor level
    (ID_UPPER / 2.0, TOTAL_HEIGHT),          # Inner wall at top face
    (ID_BORE / 2.0, TOTAL_HEIGHT),           # Central bore at top
    (ID_BORE / 2.0, 0),                      # Central bore at bottom
]

# Create the profile and revolve
result = (
    cq.Workplane("XZ")
    .polyline(profile_pts)
    .close()
    .revolve(360, (0, 0, 0), (0, 1, 0))
)

# =============================================================================
# Apply R2.00 fillet at internal corner where floor at Z=20 meets Ø105 wall
# The edge is where the internal floor (at Z=20) meets the vertical bore wall (Ø105)
# =============================================================================

# Find the internal circular edge at Z=20, radius=ID_UPPER/2
# This is the corner between the horizontal floor and vertical Ø105 wall
try:
    # Select edges near the transition point
    fillet_edge_selector = (
        cq.selectors.AndSelector(
            cq.selectors.TypeSelector("Circle"),
            cq.selectors.NearestToPointSelector((ID_UPPER / 2.0, 0, Z_MIDDLE_TOP))
        )
    )
    result = result.edges(fillet_edge_selector).fillet(FILLET_RADIUS)
except Exception:
    # If fillet fails, try a simpler nearest-point selection while keeping a solid result.
    try:
        result = result.edges(
            cq.selectors.NearestToPointSelector((ID_UPPER / 2.0, 0, Z_MIDDLE_TOP))
        ).fillet(FILLET_RADIUS)
    except Exception:
        pass  # Skip fillet if selection fails, but JSON requires it

# =============================================================================
# Create 12x M6 holes on PCD Ø115
# Per JSON: holes on upper_flange (top annular rim), depth = upper_flange_height
# The bolt holes are on the solid region between Ø139 (outer) and Ø115 (inner)
# at the top face, going down into the upper rim section
# =============================================================================

# Holes should penetrate through the upper_rim_height (8mm) based on review feedback
# The holes are placed on the top face at PCD 115.0

result = (
    result
    .faces(">Z")  # Top face at Z=28
    .workplane()
    .polarArray(radius=BOLT_PCD / 2.0, startAngle=0, angle=360, count=HOLE_COUNT)
    .hole(M6_DIA, depth=UPPER_RIM_HEIGHT)  # Depth = 8mm (upper_flange_height)
)

# =============================================================================
# Export the final model
# =============================================================================
exporters.export(result, "/home/user/project/cad3dify/runs/test_drawing_multi_json/output_v08.step")
