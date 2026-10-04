"""Construction details and actual openings for the existing station designs."""

import math
from dataclasses import replace
from promodeler.core import Box, Cylinder, Extrude, Part, Profile, Sphere, Transform


def box(parts, name, bounds, material, joint=None):
    a,b,c,d,e,f = bounds
    parts.append(Part(id=name, shape=Box(size=(b-a,d-c,f-e)), material=material,
                      transform=Transform(translation=((a+b)/2,(c+d)/2,(e+f)/2)), parent_joint=joint))


def tube(parts, name, a, b, radius=.035, material="stainless"):
    dx,dy,dz = (end-start for start,end in zip(a,b))
    if abs(dx) > 1e-8 and (abs(dy) > 1e-8 or abs(dz) > 1e-8):
        raise ValueError("Station tubes use X or the YZ plane")
    rotation = (0,0,math.pi/2) if abs(dx) > 1e-8 else (math.atan2(dz,dy),0,0)
    parts.append(Part(id=name, shape=Cylinder(radius=radius,height=math.sqrt(dx*dx+dy*dy+dz*dz),segments=16),
                      material=material, transform=Transform(translation=tuple((x+y)/2 for x,y in zip(a,b)), rotation=rotation)))


def stair_details(parts, stair):
    x0,x1 = stair["x_range_m"]
    prefix = stair["id"]
    previous = stair.get("top_floor_y_m",0)
    for tread in stair["treads"]:
        z0,z1 = tread["z_range_m"]
        top = tread["top_y_m"]
        leading = z0 if stair.get("direction_z",1) > 0 else z1-.02
        box(parts,tread["id"]+"_riser",(x0,x1,top-.02,previous,leading,leading+.02),"floor-tile")
        previous = top
    profile = stair["section_profile_zy"]
    for i,((z0,y0),(z1,y1)) in enumerate(zip(profile,profile[1:])):
        if abs(y1-y0) < 1e-8:
            box(parts,prefix+f"_landing_{i}",(x0,x1,y0-.18,y0,min(z0,z1),max(z0,z1)),"floor-tile")
        for side,x in (("w",x0-.06),("e",x1+.06)):
            for level,h in enumerate((.65,.9)):
                tube(parts,prefix+f"_handrail_{side}_{level}_{i}",(x,y0+h,z0),(x,y1+h,z1))
            for j in range(max(1,math.ceil(abs(z1-z0)/1.8))):
                t = (j+.35)/max(1,math.ceil(abs(z1-z0)/1.8))
                z,y = z0+t*(z1-z0),y0+t*(y1-y0)
                tube(parts,prefix+f"_post_{side}_{i}_{j}",(x,y+.04,z),(x,y+.9,z),.024)
    for side,x in (("w",x0-.06),("e",x1+.06)):
        for i,(z,y) in enumerate(profile):
            for level,h in enumerate((.65,.9)):
                parts.append(Part(id=prefix+f"_rail_joint_{side}_{level}_{i}",shape=Sphere(radius=.035,segments=12,rings=6),
                                  material="stainless",transform=Transform(translation=(x,y+h,z))))


def _hollow_cabin(parts, name, center_x, center_z, floor_y, joint):
    # Name the floor with the old cabin ID to preserve semantic selection.
    box(parts,name,(center_x-.8,center_x+.8,floor_y-.10,floor_y,center_z-.75,center_z+.75),"stainless",joint)
    for side in (-1,1):
        x = center_x+side*.79
        box(parts,name+f"_side_{side}",(x-.01,x+.01,floor_y,floor_y+2.2,center_z-.75,center_z+.75),"stainless",joint)
    box(parts,name+"_back",(center_x-.8,center_x+.8,floor_y,floor_y+2.2,center_z-.75,center_z-.73),"stainless",joint)
    box(parts,name+"_roof",(center_x-.8,center_x+.8,floor_y+2.18,floor_y+2.2,center_z-.75,center_z+.75),"light",joint)


def entrance_details(parts, design):
    # Slim roof beams preserve the scheduled canopy envelope. Glass replaces
    # the solid slab while stainless remains represented in the part mapping.
    for i,p in enumerate(parts):
        if p.id == "canopy-frame":
            parts[i] = replace(p,material="glass")
    for tag,bounds in (("w",(-3.5,-3.43,3.1,3.4,-12,-4.96)),("e",(3.43,3.5,3.1,3.4,-12,-4.96)),
                       ("n",(-3.5,3.5,3.1,3.4,-12,-11.93)),("s",(-3.5,3.5,3.1,3.4,-5.03,-4.96))):
        box(parts,"canopy_edge_"+tag,bounds,"stainless")
    for side,x in (("w",-3.5),("e",3.35)):
        for i,((z0,y0),(z1,y1)) in enumerate(zip(design["roof_soffit_profile_zy"],design["roof_soffit_profile_zy"][1:])):
            if z0 >= 4.08:
                continue
            if z1 > 4.08:
                y1 = y0+(y1-y0)*(4.08-z0)/(z1-z0)
                z1 = 4.08
            # u=-Z is the profile coordinate for an X extrusion.
            parts.append(Part(id=f"entry_wall_{side}_{i}",shape=Extrude(Profile(((-z1,-6.2),(-z0,-6.2),(-z0,y0),(-z1,y1))),depth=.15,axis="x"),
                              material="wall-tile",transform=Transform(translation=(x,0,0))))
            if i > 0 and side == "w":
                slope = math.atan(-(y1-y0)/(z1-z0))
                parts.append(Part(id=f"entry_soffit_{i}",shape=Box(size=(6.7,.10,math.hypot(z1-z0,y1-y0))),material="paint",
                                  transform=Transform(translation=(0,(y0+y1)/2+.05,(z0+z1)/2),rotation=(slope,0,0))))
    box(parts,"entry_bottom_landing",(-3.35,3.35,-6.18,-6,2.08,4.08),"floor-tile")
    box(parts,"lift_b1_corridor",(4.5,7.5,-6.18,-6,-7.7,4.08),"floor-tile")
    # Lower hall walls end at the concourse port; no closure spans the port.
    for side,x in (("w",-3.5),("e",7.35)):
        box(parts,"lower_hall_wall_"+side,(x,x+.15,-6,-3,4.08,14),"wall-tile")
    old = next(p for p in parts if p.id == "lift-shaft")
    parts.remove(old)
    box(parts,"lift-shaft",(4.7,4.72,-6.2,3.4,-10.3,-7.7),"glass")
    box(parts,"lift-shaft_e",(7.28,7.3,-6.2,3.4,-10.3,-7.7),"glass")
    box(parts,"lift-shaft_back",(4.7,7.3,-6.2,3.4,-10.3,-10.28),"glass")
    box(parts,"lift-shaft_front_top",(4.7,7.3,2.1,3.4,-7.72,-7.7),"glass")
    box(parts,"lift-shaft_front_mid",(4.7,7.3,-3.9,0,-7.72,-7.7),"glass")
    for tag,a,b in (("w",4.7,5.55),("e",6.45,7.3)):
        box(parts,"lift-shaft_front_"+tag,(a,b,-6.2,2.1,-7.72,-7.7),"glass")
    cabin = next(p for p in parts if p.id == "lift_cabin")
    parts.remove(cabin)
    _hollow_cabin(parts,"lift_cabin",6.,-9.,-6.,cabin.parent_joint)
    for i,p in enumerate(parts):
        if p.id == "lift_door_left":
            parts[i] = replace(p,transform=replace(p.transform,translation=(5.775,1.05,-7.7)))
    box(parts,"lift_street_door_right",(6,6.45,0,2.1,-7.714,-7.704),"stainless")
    # Drainage at the stair foot and the reference's exposed overhead services.
    box(parts,"entry_drain_frame",(-3.3,3.3,-5.999,-5.986,3.73,3.95),"stainless")
    for i in range(44):
        x=-3.25+i*.15
        box(parts,f"entry_drain_slot_{i}",(x,x+.045,-5.985,-5.982,3.75,3.93),"rubber")
    for x in (-2.85,2.9):
        for i,((z0,y0),(z1,y1)) in enumerate(zip(design["roof_soffit_profile_zy"],design["roof_soffit_profile_zy"][1:])):
            tube(parts,f"entry_service_pipe_{x}_{i}",(x,y0-.18,z0),(x,y1-.18,z1),.045)
            for j,z in enumerate((z0+.15,z1-.15)):
                y=y0+(z-z0)*(y1-y0)/(z1-z0)-.18
                parts.append(Part(id=f"entry_pipe_collar_{x}_{i}_{j}",shape=Sphere(radius=.055,segments=12,rings=6),
                                  material="stainless",transform=Transform(translation=(x,y,z))))


def concourse_details(parts, design):
    for tag,z0,z1 in (("A",-1.92,0.),("B",20.,21.92)):
        box(parts,"bank_"+tag+"_bottom_link",(-3,3,-6.18,-6,z0,z1),"floor-tile")
    old = next(p for p in parts if p.id == "paid_lift_cabin")
    parts.remove(old)
    _hollow_cabin(parts,"paid_lift_cabin",0.,10.,-6.,old.parent_joint)
    for side in (-1,1):
        x=side*1.29
        box(parts,f"paid_lift_glass_{side}",(x-.01,x+.01,-6.2,2.8,8.7,11.3),"glass")
    box(parts,"paid_lift_back",(-1.3,1.3,-6.2,2.8,8.7,8.72),"glass")
    for tag,x0,x1 in (("w",-1.3,-.45),("e",.45,1.3)):
        box(parts,"paid_lift_front_"+tag,(x0,x1,-6.2,2.8,11.28,11.3),"glass")
    for tag,y0,y1 in (("mid",-3.9,0),("head",2.1,2.8)):
        box(parts,"paid_lift_front_"+tag,(-.45,.45,y0,y1,11.28,11.3),"glass")
