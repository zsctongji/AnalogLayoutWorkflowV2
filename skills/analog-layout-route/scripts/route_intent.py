#!/usr/bin/env python3
"""Build and validate deterministic PDK-aware analog routing intents."""
from __future__ import annotations
import argparse, hashlib, html, json, math, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROFILE_SCHEMA="analog-pdk-profile/v1"; ACCESS_SCHEMA="analog-layout-align.terminal-access/v1"
SPEC_SCHEMA="analog-layout-route.spec/v1"; INTENT_SCHEMA="analog-layout-route.intent/v1"
FP_KEYS=("technology","manufacturing_grid_um","layers","layer_purposes","layer_functions","constraints","routing_layers","vias")

def load(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def digest(value):
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()
def fingerprint(p): return digest({k:p[k] for k in FP_KEYS})
def snap(v,g): return round(round(float(v)/g)*g,12)
def snap_down(v,g): return round(math.floor((float(v)+1e-12)/g)*g,12)
def snap_up(v,g): return round(math.ceil((float(v)-1e-12)/g)*g,12)
def on_segment(p,a,b,t):
    inside=min(a[0],b[0])-t<=p[0]<=max(a[0],b[0])+t and min(a[1],b[1])-t<=p[1]<=max(a[1],b[1])+t
    aligned=(abs(a[0]-b[0])<=t and abs(p[0]-a[0])<=t) or (abs(a[1]-b[1])<=t and abs(p[1]-a[1])<=t)
    return inside and aligned
def floor(rules,label):
    vals=[float(r["value"]) for r in rules if isinstance(r.get("value"),(int,float)) and not r.get("parameters")]
    if not vals: raise ValueError(f"{label} has no unconditional scalar rule")
    return max(vals)
def segrect(a,b,w):
    h=w/2; return min(a[0],b[0])-h,min(a[1],b[1])-h,max(a[0],b[0])+h,max(a[1],b[1])+h
def rectdist(a,b):
    dx=max(a[0]-b[2],b[0]-a[2],0); dy=max(a[1]-b[3],b[1]-a[3],0)
    return math.hypot(dx,dy)
def normbbox(value,grid):
    if not isinstance(value,list) or len(value)!=2 or any(not isinstance(p,list) or len(p)!=2 for p in value):
        raise ValueError("invalid extension_bbox_um")
    x0,y0=snap_down(value[0][0],grid),snap_down(value[0][1],grid); x1,y1=snap_up(value[1][0],grid),snap_up(value[1][1],grid)
    if x1<=x0 or y1<=y0: raise ValueError("extension_bbox_um must have positive area")
    return [[x0,y0],[x1,y1]]
def bbox_contains(bbox,point,tol=1e-12):
    return bbox[0][0]-tol<=point[0]<=bbox[1][0]+tol and bbox[0][1]-tol<=point[1]<=bbox[1][1]+tol
def layer_floor(profile,definition,layer):
    values=[]
    for rule in profile.get("constraints",{}).get("rules",[]):
        if rule.get("definition")==definition and rule.get("layers")==[layer] and not rule.get("parameters") and isinstance(rule.get("value"),(int,float)):
            values.append(float(rule["value"]))
    if not values: raise ValueError(f"{layer} has no unconditional scalar {definition} rule")
    return max(values)
def terminal_islands(instance,terminal,term):
    islands=term.get("pin_islands")
    if islands:
        return islands
    return [{"id":f"{instance}:{terminal}:legacy","candidate_centers":term.get("candidate_centers",[]),
        "selected_center":term.get("selected_center"),"access_layers":term.get("access_layers",[]),"legacy":True}]
def resolve_island(instance,terminal,term,island_id,xy,errors,label):
    islands=terminal_islands(instance,terminal,term)
    if island_id is not None:
        matches=[item for item in islands if item.get("id")==island_id]
        if len(matches)!=1:
            errors.append(f"{label}: unknown pin_island_id {island_id!r}"); return None
        return matches[0]
    matches=[]
    if xy is not None:
        matches=[item for item in islands if xy in item.get("candidate_centers",[])]
    if len(matches)==1: return matches[0]
    if len(islands)==1: return islands[0]
    errors.append(f"{label}: pin_island_id is required for a multi-island terminal")
    return None
def contact_bbox(pin_xy,contact_xy,required_w,required_h,min_width,grid):
    width=max(required_w,min_width); height=max(required_h,min_width)
    if pin_xy==contact_xy:
        return normbbox([[contact_xy[0]-width/2,contact_xy[1]-height/2],[contact_xy[0]+width/2,contact_xy[1]+height/2]],grid)
    if pin_xy[1]==contact_xy[1]:
        return normbbox([[min(pin_xy[0],contact_xy[0])-width/2,pin_xy[1]-height/2],
            [max(pin_xy[0],contact_xy[0])+width/2,pin_xy[1]+height/2]],grid)
    if pin_xy[0]==contact_xy[0]:
        return normbbox([[pin_xy[0]-width/2,min(pin_xy[1],contact_xy[1])-height/2],
            [pin_xy[0]+width/2,max(pin_xy[1],contact_xy[1])+height/2]],grid)
    raise ValueError("pin_xy_um and xy_um must form a Manhattan extension")

def bend_count(points):
    bends=0
    for a,b,c in zip(points,points[1:],points[2:]):
        first=(b[0]-a[0],b[1]-a[1]); second=(c[0]-b[0],c[1]-b[1])
        if (first[0]==0)!=(second[0]==0): bends+=1
    return bends

def box(points):
    if not points: return None
    return [[min(p[0] for p in points),min(p[1] for p in points)],
            [max(p[0] for p in points),max(p[1] for p in points)]]

def box_span(bbox):
    return [bbox[1][0]-bbox[0][0],bbox[1][1]-bbox[0][1]] if bbox else [0.0,0.0]

def point_in_route_metal(point,route,tol=1e-12):
    return any(bbox_contains([[r[0],r[1]],[r[2],r[3]]],point,tol)
        for r in (segrect(a,b,route["width_um"]) for a,b in zip(route["points_um"],route["points_um"][1:])))

def routes_touch(one,two,tol=1e-12):
    if one["layer"]!=two["layer"]: return False
    return any(rectdist(segrect(a,b,one["width_um"]),segrect(c,d,two["width_um"]))<=tol
        for a,b in zip(one["points_um"],one["points_um"][1:])
        for c,d in zip(two["points_um"],two["points_um"][1:]))

def physical_components(routes,vias,landings,grid):
    """Return same-net conductive components across metal, vias, and contacts."""
    by_net={}
    for kind,items in (("route",routes),("via",vias),("landing",landings)):
        for item in items: by_net.setdefault(item["net"],[]).append((kind,item))
    result={}
    for net,nodes in by_net.items():
        edges=[set() for _ in nodes]
        for i,(kind_a,a) in enumerate(nodes):
            for j in range(i+1,len(nodes)):
                kind_b,b=nodes[j]; connected=False
                if kind_a==kind_b=="route": connected=routes_touch(a,b,grid/2)
                elif {kind_a,kind_b}=={"route","via"}:
                    route=a if kind_a=="route" else b; via=a if kind_a=="via" else b
                    connected=route["layer"] in (via["layer1"],via["layer2"]) and point_in_route_metal(via["xy_um"],route,grid/2)
                elif {kind_a,kind_b}=={"route","landing"}:
                    route=a if kind_a=="route" else b; landing=a if kind_a=="landing" else b
                    connected=route["layer"]==landing["target_layer"] and point_in_route_metal(landing["xy_um"],route,grid/2)
                elif kind_a==kind_b=="via":
                    connected=a["xy_um"]==b["xy_um"] and bool({a["layer1"],a["layer2"]}&{b["layer1"],b["layer2"]})
                elif {kind_a,kind_b}=={"via","landing"}:
                    via=a if kind_a=="via" else b; landing=a if kind_a=="landing" else b
                    connected=via["xy_um"]==landing["xy_um"] and bool({via["layer1"],via["layer2"]}&{landing["source_layer"],landing["target_layer"]})
                if connected: edges[i].add(j); edges[j].add(i)
        unseen=set(range(len(nodes))); components=[]
        while unseen:
            seed=unseen.pop(); stack=[seed]; member={seed}
            while stack:
                for other in edges[stack.pop()]:
                    if other in unseen: unseen.remove(other); member.add(other); stack.append(other)
            components.append(sorted(nodes[index][1]["id"] for index in member))
        result[net]=components
    return result

def preferred_directions(profile,spec):
    result={}
    declared=spec.get("preferred_directions",{})
    for item in profile.get("routing_layers",[]):
        layer=item.get("layer"); direction=declared.get(layer) or item.get("preferred_direction")
        if isinstance(direction,str) and direction.lower() in ("horizontal","vertical"):
            result[layer]=direction.lower(); continue
        match=re.search(r"(\d+)$",str(layer))
        if match: result[layer]="vertical" if int(match.group(1))%2 else "horizontal"
    return result

def build(profile:dict[str,Any], access:dict[str,Any], spec:dict[str,Any])->dict[str,Any]:
    errors=[]; warnings=[]
    if profile.get("schema")!=PROFILE_SCHEMA: errors.append(f"unsupported profile schema: {profile.get('schema')!r}")
    expected=fingerprint(profile) if all(k in profile for k in FP_KEYS) else ""
    actual=profile.get("fingerprint",{}).get("value")
    if expected!=actual: errors.append("profile fingerprint mismatch")
    if not profile.get("validation",{}).get("structurally_valid"): errors.append("profile is not structurally valid")
    if not profile.get("coverage",{}).get("basic_routing_ready"): errors.append("profile is not basic-routing-ready")
    if not profile.get("boundaries",{}).get("may_drive_automatic_routing"): errors.append("profile may not drive automatic routing")
    if access.get("schema")!=ACCESS_SCHEMA: errors.append(f"unsupported terminal-access schema: {access.get('schema')!r}")
    if spec.get("schema")!=SPEC_SCHEMA: errors.append(f"unsupported route spec schema: {spec.get('schema')!r}")
    if spec.get("target")!=access.get("target"): errors.append(f"target mismatch: spec={spec.get('target')} access={access.get('target')}")
    grid=float(profile.get("manufacturing_grid_um") or .001)
    layers={x["layer"]:x for x in profile.get("routing_layers",[])}; viadefs={x["name"]:x for x in profile.get("vias",[])}
    lpps={(x.get("layer"),x.get("purpose")) for x in profile.get("layer_purposes",[])}
    instances={x["name"]:x for x in access.get("instances",[])}
    routes=[]; ids=set(); max_delta=0.0
    for i,raw in enumerate(spec.get("routes",[])):
        rid=str(raw.get("id") or f"route_{i}"); layer=raw.get("layer")
        if rid in ids: errors.append(f"duplicate route id {rid}")
        ids.add(rid); rules=layers.get(layer)
        if not rules: errors.append(f"route {rid}: unknown routing layer {layer!r}"); continue
        try: minw=floor(rules.get("minimum_width_rules",[]),f"{layer} minimum width"); mins=floor(rules.get("minimum_spacing_rules",[]),f"{layer} minimum spacing")
        except ValueError as exc: errors.append(f"route {rid}: {exc}"); continue
        purpose=raw.get("purpose","drawing")
        if lpps and (layer,purpose) not in lpps: errors.append(f"route {rid}: unknown layer-purpose {layer}/{purpose}")
        width=float(raw.get("width_um") if raw.get("width_um") is not None else minw)
        if width+1e-12<minw: errors.append(f"route {rid}: width {width} < minimum {minw} um")
        rawpts=raw.get("points_um",[])
        if not isinstance(rawpts,list) or len(rawpts)<2 or any(not isinstance(p,list) or len(p)!=2 for p in rawpts): errors.append(f"route {rid}: invalid points_um"); continue
        points=[[snap(p[0],grid),snap(p[1],grid)] for p in rawpts]
        for p,s in zip(rawpts,points): max_delta=max(max_delta,abs(float(p[0])-s[0]),abs(float(p[1])-s[1]))
        length=0.0
        for a,b in zip(points,points[1:]):
            if a==b: errors.append(f"route {rid}: zero-length segment at {a}")
            if a[0]!=b[0] and a[1]!=b[1]: errors.append(f"route {rid}: non-Manhattan segment {a}->{b}")
            length+=abs(a[0]-b[0])+abs(a[1]-b[1])
        routes.append({"id":rid,"net":str(raw.get("net","")),"layer":layer,"purpose":purpose,"width_um":width,
            "profile_min_width_um":minw,"profile_min_spacing_um":mins,"points_um":points,"length_um":round(length,12),"access":raw.get("access",[])})
    vias=[]
    for i,raw in enumerate(spec.get("vias",[])):
        vid=str(raw.get("id") or f"via_{i}"); vd=viadefs.get(raw.get("via")); xy0=raw.get("xy_um")
        if vid in ids: errors.append(f"duplicate object id {vid}")
        ids.add(vid)
        if not vd: errors.append(f"via {vid}: unknown profile via {raw.get('via')!r}"); continue
        if not vd.get("standard_geometry"): errors.append(f"via {vid}: no normalized geometry")
        if not isinstance(xy0,list) or len(xy0)!=2: errors.append(f"via {vid}: invalid xy_um"); continue
        xy=[snap(xy0[0],grid),snap(xy0[1],grid)]; max_delta=max(max_delta,abs(float(xy0[0])-xy[0]),abs(float(xy0[1])-xy[1]))
        vias.append({"id":vid,"net":str(raw.get("net","")),"via":raw.get("via"),"xy_um":xy,"layer1":vd.get("layer1"),"layer2":vd.get("layer2"),"standard_geometry":vd.get("standard_geometry")})
    landings=[]; landing_covered=set()
    for i,raw in enumerate(spec.get("contact_landings",[])):
        lid=str(raw.get("id") or f"landing_{i}"); label=f"contact landing {lid}"
        if lid in ids: errors.append(f"duplicate object id {lid}")
        ids.add(lid)
        inst=instances.get(raw.get("instance")); terminal=str(raw.get("terminal", "")); term=inst.get("terminals",{}).get(terminal) if inst else None
        if not term: errors.append(f"{label}: terminal not found"); continue
        net=str(raw.get("net", ""))
        if term.get("net")!=net: errors.append(f"{label}: expected net {term.get('net')!r}, got {net!r}")
        vd=viadefs.get(raw.get("via")); xy0=raw.get("xy_um")
        if not vd: errors.append(f"{label}: unknown profile via {raw.get('via')!r}"); continue
        geometry=vd.get("standard_geometry")
        if not geometry: errors.append(f"{label}: via has no normalized geometry"); continue
        if not isinstance(xy0,list) or len(xy0)!=2: errors.append(f"{label}: invalid xy_um"); continue
        xy=[snap(xy0[0],grid),snap(xy0[1],grid)]
        pin0=raw.get("pin_xy_um")
        pin_xy=[snap(pin0[0],grid),snap(pin0[1],grid)] if isinstance(pin0,list) and len(pin0)==2 else None
        island=resolve_island(str(raw.get("instance")),terminal,term,raw.get("pin_island_id"),pin_xy,errors,label)
        if not island: continue
        if pin_xy is None:
            selected=island.get("selected_center")
            pin_xy=[snap(selected[0],grid),snap(selected[1],grid)] if isinstance(selected,list) and len(selected)==2 else None
        candidates=[[snap(p[0],grid),snap(p[1],grid)] for p in island.get("candidate_centers",[])]
        if pin_xy not in candidates: errors.append(f"{label}: pin_xy_um {pin_xy} is not in physical island {island.get('id')}"); continue
        source=str(raw.get("source_layer") or (island.get("access_layers") or [None])[0])
        if source not in island.get("access_layers",[]): errors.append(f"{label}: source layer {source!r} is not available on the physical island")
        if source==vd.get("layer1"): target=vd.get("layer2"); enclosure=geometry.get("layer1_enclosure_um")
        elif source==vd.get("layer2"): target=vd.get("layer1"); enclosure=geometry.get("layer2_enclosure_um")
        else: errors.append(f"{label}: via {vd.get('name')} does not touch source layer {source}"); continue
        if target not in layers: errors.append(f"{label}: target layer {target!r} is not a routing layer")
        purpose=raw.get("purpose","drawing")
        if lpps and (source,purpose) not in lpps: errors.append(f"{label}: unknown layer-purpose {source}/{purpose}")
        cut=geometry.get("cut_size_um") or []
        if not (isinstance(cut,list) and len(cut)==2 and isinstance(enclosure,list) and len(enclosure)==2):
            errors.append(f"{label}: incomplete via cut/enclosure geometry"); continue
        req_w=float(cut[0])+2*float(enclosure[0]); req_h=float(cut[1])+2*float(enclosure[1])
        try:
            min_width=layer_floor(profile,"minWidth",source)
            bbox=normbbox(raw["extension_bbox_um"],grid) if raw.get("extension_bbox_um") is not None else contact_bbox(pin_xy,xy,req_w,req_h,min_width,grid)
        except (ValueError,KeyError) as exc: errors.append(f"{label}: {exc}"); continue
        contact_required=[[xy[0]-req_w/2,xy[1]-req_h/2],[xy[0]+req_w/2,xy[1]+req_h/2]]
        if not bbox_contains(bbox,pin_xy): errors.append(f"{label}: extension does not overlap selected pin access")
        if not (bbox_contains(bbox,contact_required[0]) and bbox_contains(bbox,contact_required[1])):
            errors.append(f"{label}: extension does not satisfy source-layer via enclosure")
        if min(bbox[1][0]-bbox[0][0],bbox[1][1]-bbox[0][1])+1e-12<min_width:
            errors.append(f"{label}: extension width is below {source} minimum {min_width} um")
        touched=any(r["net"]==net and r["layer"]==target and any(on_segment(xy,a,b,grid/2) for a,b in zip(r["points_um"],r["points_um"][1:])) for r in routes)
        if not touched: errors.append(f"{label}: no {target} route on net {net} touches contact {xy}")
        landing={"id":lid,"net":net,"instance":raw.get("instance"),"terminal":terminal,
            "pin_island_id":island.get("id"),"pin_xy_um":pin_xy,"source_layer":source,
            "target_layer":target,"purpose":purpose,"extension_bbox_um":bbox,
            "via":raw.get("via"),"xy_um":xy,"standard_geometry":geometry,"profile_min_width_um":min_width}
        landings.append(landing); landing_covered.add((str(raw.get("instance")),terminal,island.get("id")))
    for via in vias:
        connected=any(r["net"]==via["net"] and r["layer"] in (via["layer1"],via["layer2"]) and any(on_segment(via["xy_um"],a,b,grid/2) for a,b in zip(r["points_um"],r["points_um"][1:])) for r in routes)
        if not connected: errors.append(f"via {via['id']}: no same-net route touches {via['xy_um']} on {via['layer1']}/{via['layer2']}")
    route_covered=set()
    for route in routes:
        for att in route["access"]:
            label=f"route {route['id']} access {att.get('instance')}/{att.get('terminal')}"
            inst=instances.get(att.get("instance")); term=inst.get("terminals",{}).get(att.get("terminal")) if inst else None
            if not term: errors.append(f"{label}: terminal not found"); continue
            if term.get("net")!=route["net"]: errors.append(f"{label}: expected net {term.get('net')!r}, got {route['net']!r}")
            xy0=att.get("xy_um",term.get("selected_center")); xy=[snap(xy0[0],grid),snap(xy0[1],grid)] if isinstance(xy0,list) and len(xy0)==2 else None
            island=resolve_island(str(att.get("instance")),str(att.get("terminal")),term,att.get("pin_island_id"),xy,errors,label)
            if not island: continue
            candidates=[[snap(p[0],grid),snap(p[1],grid)] for p in island.get("candidate_centers",[])]
            if xy not in candidates: errors.append(f"{label}: {xy} is not a candidate center"); continue
            if not any(on_segment(xy,a,b,grid/2) for a,b in zip(route["points_um"],route["points_um"][1:])): errors.append(f"{label}: point is not covered by route")
            access_layers=set(island.get("access_layers",[]))
            if route["layer"] not in access_layers:
                ok=any(v["net"]==route["net"] and v["xy_um"]==xy and route["layer"] in (v["layer1"],v["layer2"]) and bool(access_layers & {v["layer1"],v["layer2"]}) for v in vias)
                ok=ok or any(l["net"]==route["net"] and l["xy_um"]==xy and l["target_layer"]==route["layer"] and l["source_layer"] in access_layers for l in landings)
                if not ok: errors.append(f"{label}: no profile via transitions {sorted(access_layers)} to {route['layer']} at {xy}")
            route_covered.add((str(att.get("instance")),str(att.get("terminal")),island.get("id")))
    routed_nets={route["net"] for route in routes}
    declared_required=spec.get("required_nets")
    if declared_required is None:
        required_nets=set(routed_nets)
    elif not isinstance(declared_required,list) or any(not isinstance(net,str) or not net for net in declared_required):
        errors.append("required_nets must be a list of non-empty net names"); required_nets=set()
    else:
        required_nets=set(declared_required)
        if len(required_nets)!=len(declared_required): errors.append("required_nets contains duplicates")
        for net in sorted(required_nets-routed_nets): errors.append(f"required net {net} has no route")
    waiver_map={(str(item.get("instance")),str(item.get("terminal"))):item for item in spec.get("terminal_waivers",[]) if str(item.get("reason","")).strip() and str(item.get("evidence","")).strip()}
    unresolved_terminals=[]
    for instance in access.get("instances",[]):
        missing=set(instance.get("missing_master_terminals",[])); intended=instance.get("intent_terminals",{})
        for terminal in sorted(missing):
            net=intended.get(terminal)
            if net in required_nets and (instance.get("name"),terminal) not in waiver_map:
                item={"instance":instance.get("name"),"terminal":terminal,"net":net}; unresolved_terminals.append(item)
                errors.append(f"unresolved physical terminal {instance.get('name')}/{terminal} on required net {net}; add verified body/internal-tie evidence or expose access")
    covered=route_covered|landing_covered
    required=[]
    for instance in access.get("instances",[]):
        for terminal,term in instance.get("terminals",{}).items():
            if term.get("net") not in required_nets: continue
            for island in terminal_islands(instance.get("name"),terminal,term):
                key=(instance.get("name"),terminal,island.get("id")); required.append(key)
                if key not in covered: errors.append(f"uncovered physical pin island {key[0]}/{key[1]}/{key[2]} on routed net {term.get('net')}")
    connectivity=physical_components(routes,vias,landings,grid)
    for net in sorted(required_nets):
        components=connectivity.get(net,[])
        if len(components)>1:
            summary=[component[:4]+([f"...+{len(component)-4}"] if len(component)>4 else []) for component in components]
            errors.append(f"net {net}: disconnected physical routing has {len(components)} components {summary}")
    for i,one in enumerate(routes):
        for two in routes[i+1:]:
            if one["net"]==two["net"] or one["layer"]!=two["layer"]: continue
            req=max(one["profile_min_spacing_um"],two["profile_min_spacing_um"]); bad=None
            for a,b in zip(one["points_um"],one["points_um"][1:]):
                for c,d in zip(two["points_um"],two["points_um"][1:]):
                    gap=rectdist(segrect(a,b,one["width_um"]),segrect(c,d,two["width_um"]))
                    if gap+1e-12<req: bad=gap; break
                if bad is not None: break
            if bad is not None: errors.append(f"routes {one['id']}/{two['id']}: cross-net gap {bad:.6g} < {req:.6g} um")
    metrics={}; route_points={}; terminal_points={}; preferred=preferred_directions(profile,spec); direction_lengths={}
    for r in routes:
        m=metrics.setdefault(r["net"],{"path_length_um":0.0,"route_count":0,"via_count":0,"contact_landing_count":0,"bend_count":0,"layer_lengths_um":{},"via_types":{}})
        m["path_length_um"]+=r["length_um"]; m["route_count"]+=1; m["bend_count"]+=bend_count(r["points_um"])
        m["layer_lengths_um"][r["layer"]]=m["layer_lengths_um"].get(r["layer"],0.0)+r["length_um"]
        route_points.setdefault(r["net"],[]).extend(r["points_um"])
        terminal_points.setdefault(r["net"],[]).extend([att.get("xy_um") for att in r["access"] if isinstance(att.get("xy_um"),list)])
        for a,b in zip(r["points_um"],r["points_um"][1:]):
            length=abs(a[0]-b[0])+abs(a[1]-b[1]); direction="horizontal" if a[1]==b[1] else "vertical"
            bucket=direction_lengths.setdefault(r["net"],{}).setdefault(r["layer"],{"horizontal_um":0.0,"vertical_um":0.0,"off_preference_um":0.0})
            bucket[direction+"_um"]+=length
            if preferred.get(r["layer"]) and preferred[r["layer"]]!=direction: bucket["off_preference_um"]+=length
    for v in vias:
        m=metrics.setdefault(v["net"],{"path_length_um":0.0,"route_count":0,"via_count":0,"contact_landing_count":0,"bend_count":0,"layer_lengths_um":{},"via_types":{}})
        m["via_count"]+=1; m["via_types"][v["via"]]=m["via_types"].get(v["via"],0)+1
    for l in landings:
        m=metrics.setdefault(l["net"],{"path_length_um":0.0,"route_count":0,"via_count":0,"contact_landing_count":0,"bend_count":0,"layer_lengths_um":{},"via_types":{}})
        m["via_count"]+=1; m["contact_landing_count"]+=1; m["via_types"][l["via"]]=m["via_types"].get(l["via"],0)+1
        terminal_points.setdefault(l["net"],[]).append(l["pin_xy_um"])
    for net,m in metrics.items():
        m["path_length_um"]=round(m["path_length_um"],12)
        m["layer_lengths_um"]={layer:round(length,12) for layer,length in sorted(m["layer_lengths_um"].items())}
        m["route_bbox_um"]=box(route_points.get(net,[])); m["route_bbox_span_um"]=[round(x,12) for x in box_span(m["route_bbox_um"])]
        terminal_bbox=box(terminal_points.get(net,[])); m["terminal_bbox_um"]=terminal_bbox
        m["physical_access_count"]=len(terminal_points.get(net,[]))
        hpwl=sum(box_span(terminal_bbox)); m["terminal_hpwl_um"]=round(hpwl,12)
        m["detour_ratio"]=round(m["path_length_um"]/hpwl,12) if hpwl>1e-12 else None
        if terminal_bbox and m["route_bbox_um"]:
            rb=m["route_bbox_um"]; tb=terminal_bbox
            m["bbox_excursion_um"]=round(max(tb[0][0]-rb[0][0],tb[0][1]-rb[0][1],rb[1][0]-tb[1][0],rb[1][1]-tb[1][1],0),12)
        else: m["bbox_excursion_um"]=None
        m["connected_component_count"]=len(connectivity.get(net,[]))
        m["direction_lengths_um"]={layer:{key:round(value,12) for key,value in values.items()} for layer,values in sorted(direction_lengths.get(net,{}).items())}
        off=sum(values["off_preference_um"] for values in direction_lengths.get(net,{}).values())
        m["off_preference_length_um"]=round(off,12)
        m["off_preference_ratio"]=round(off/m["path_length_um"],12) if m["path_length_um"]>1e-12 else 0.0
    for rule in spec.get("net_constraints",[]):
        net=str(rule.get("net","")); metric=metrics.get(net)
        if not metric: errors.append(f"net constraint references unrouted net {net}"); continue
        if rule.get("max_detour_ratio") is not None:
            if metric["detour_ratio"] is None: errors.append(f"net {net}: detour ratio is undefined for zero terminal HPWL")
            elif metric["detour_ratio"]>float(rule["max_detour_ratio"])+1e-12: errors.append(f"net {net}: detour ratio {metric['detour_ratio']:.6g} > {float(rule['max_detour_ratio']):.6g}")
        if rule.get("max_bends") is not None and metric["bend_count"]>int(rule["max_bends"]): errors.append(f"net {net}: bend count {metric['bend_count']} > {int(rule['max_bends'])}")
        if rule.get("max_bbox_excursion_um") is not None and (metric["bbox_excursion_um"] is None or metric["bbox_excursion_um"]>float(rule["max_bbox_excursion_um"])+1e-12): errors.append(f"net {net}: bbox excursion exceeds {float(rule['max_bbox_excursion_um']):.6g} um")
    matching=[]
    for pair in spec.get("matching",[]):
        a,b=pair.get("first_net"),pair.get("second_net"); ma,mb=metrics.get(a,{}),metrics.get(b,{})
        present=a in metrics and b in metrics
        if not present: errors.append(f"matching {a}/{b}: both nets must have route geometry")
        dl=abs(float(ma.get("path_length_um",0))-float(mb.get("path_length_um",0))); dv=abs(int(ma.get("via_count",0))-int(mb.get("via_count",0)))
        limit=float(pair.get("max_length_delta_um",0)); layers=set(ma.get("layer_lengths_um",{}))|set(mb.get("layer_lengths_um",{}))
        layer_deltas={layer:round(abs(ma.get("layer_lengths_um",{}).get(layer,0)-mb.get("layer_lengths_um",{}).get(layer,0)),12) for layer in sorted(layers)}
        max_layer_delta=max(layer_deltas.values(),default=0.0); bend_delta=abs(int(ma.get("bend_count",0))-int(mb.get("bend_count",0)))
        via_types=set(ma.get("via_types",{}))|set(mb.get("via_types",{})); via_type_delta=sum(abs(ma.get("via_types",{}).get(v,0)-mb.get("via_types",{}).get(v,0)) for v in via_types)
        spans_a=ma.get("route_bbox_span_um",[0,0]); spans_b=mb.get("route_bbox_span_um",[0,0]); bbox_span_delta=max((abs(x-y) for x,y in zip(spans_a,spans_b)),default=0.0)
        route_count_delta=abs(int(ma.get("route_count",0))-int(mb.get("route_count",0))); access_count_delta=abs(int(ma.get("physical_access_count",0))-int(mb.get("physical_access_count",0)))
        per_layer_limit=float(pair.get("max_per_layer_length_delta_um",limit)); bend_limit=int(pair.get("max_bend_delta",0)); via_type_limit=int(pair.get("max_via_type_delta",pair.get("max_via_delta",0))); route_count_limit=int(pair.get("max_route_count_delta",0)); access_count_limit=int(pair.get("max_access_count_delta",0)); bbox_limit=pair.get("max_bbox_span_delta_um")
        bbox_ok=bbox_limit is None or bbox_span_delta<=float(bbox_limit)+1e-12
        ok=(present and dl<=limit+1e-12 and dv<=int(pair.get("max_via_delta",0)) and max_layer_delta<=per_layer_limit+1e-12 and bend_delta<=bend_limit and via_type_delta<=via_type_limit and route_count_delta<=route_count_limit and access_count_delta<=access_count_limit and bbox_ok)
        matching.append({**pair,"length_delta_um":round(dl,12),"via_delta":dv,"per_layer_length_delta_um":layer_deltas,"max_per_layer_length_delta_um_observed":round(max_layer_delta,12),"bend_delta":bend_delta,"via_type_delta":via_type_delta,"route_count_delta":route_count_delta,"physical_access_count_delta":access_count_delta,"bbox_span_delta_um":round(bbox_span_delta,12),"pass":ok})
        if not ok and present: errors.append(f"matching {a}/{b}: total-length delta {dl:.6g} um, max per-layer delta {max_layer_delta:.6g} um, bend delta {bend_delta}, via delta {dv}, via-type delta {via_type_delta}, route-count delta {route_count_delta}, access-count delta {access_count_delta}, bbox-span delta {bbox_span_delta:.6g} um")
    unknown=profile.get("coverage",{}).get("unknown_signoff_categories",[])
    if unknown: warnings.append("profile lacks signoff coverage: "+", ".join(unknown))
    if max_delta>grid/1000: warnings.append(f"coordinates snapped to {grid:g} um grid; max delta {max_delta:g} um")
    pair_members={str(pair.get(key)) for pair in spec.get("matching",[]) for key in ("first_net","second_net")}
    for net,m in sorted(metrics.items()):
        if m.get("off_preference_length_um",0)>grid/2:
            reason="matched-topology override" if net in pair_members else "review and document the deviation"
            warnings.append(f"net {net}: {m['off_preference_ratio']:.1%} of routed length is off preferred layer direction ({reason})")
    planning_evidence=spec.get("planning_evidence")
    if isinstance(planning_evidence,dict) and planning_evidence.get("obstacle_coverage",{}).get("live_snapshot") is False:
        review=planning_evidence.get("offline_obstacle_review") or {}
        if not (review.get("reviewed_live_target") is True and str(review.get("basis","")).strip()):
            warnings.append("offline obstacle snapshot has not been reconciled with live PCell bodies, existing routes, and top-level shapes; materialization is blocked")
    warnings.append("static checks are not foundry DRC/LVS and exclude arbitrary PCell obstructions")
    valid=not errors
    return {"schema":INTENT_SCHEMA,"generated_at":datetime.now(timezone.utc).isoformat(),"target":spec.get("target"),
        "sources":{"profile_fingerprint":actual,"profile_sha256":digest(profile),"terminal_access_sha256":digest(access),"route_spec_sha256":digest(spec)},
        "manufacturing_grid_um":grid,"preferred_directions":preferred,"planning_evidence":planning_evidence,"required_nets":sorted(required_nets),"routes":routes,"vias":vias,"contact_landings":landings,"net_metrics":metrics,"matching":matching,
        "symmetry_groups":spec.get("symmetry_groups",[]),"review_requirements":{"svg_check_required":True},
        "physical_access_coverage":{"required_count":len(required),"covered_count":len(set(required)&covered),
            "complete":set(required)<=covered,"required":[{"instance":x[0],"terminal":x[1],"pin_island_id":x[2]} for x in required]},
        "physical_connectivity":{"components_by_net":connectivity,"complete":all(len(connectivity.get(net,[]))==1 for net in required_nets)},
        "terminal_obligations":{"unresolved":unresolved_terminals,"waivers":list(waiver_map.values()),"complete":not unresolved_terminals},
        "coverage":{"checked":["profile identity/readiness","required-net and physical pin-island coverage","whole-net conductive connectivity","minimum width","Manhattan/grid geometry","via transitions","poly/contact source enclosure","basic same-layer spacing","declared directness limits","total/per-layer/bend/via-type/bbox matching"],"not_checked":["arbitrary PCell obstructions","conditional/EOL/notch rules","environmental coupling symmetry","density","antenna","electromigration","substrate coupling","DRC","LVS"]},
        "validation":{"valid":valid,"errors":sorted(set(errors)),"warnings":sorted(set(warnings))},"decision":{"status":"READY_FOR_REVIEW" if valid else "BLOCKED","requires_review":True,"requires_foundry_drc_lvs":True}}

def validate(profile,intent):
    errors=[]
    if intent.get("schema")!=INTENT_SCHEMA: errors.append("unsupported intent schema")
    if fingerprint(profile)!=profile.get("fingerprint",{}).get("value"): errors.append("profile fingerprint mismatch")
    if intent.get("sources",{}).get("profile_fingerprint")!=profile.get("fingerprint",{}).get("value"): errors.append("intent profile fingerprint drift")
    if not intent.get("validation",{}).get("valid"): errors.append("intent is not valid")
    if intent.get("decision",{}).get("status")!="READY_FOR_REVIEW": errors.append("intent is not READY_FOR_REVIEW")
    if not intent.get("physical_connectivity",{}).get("complete"): errors.append("intent lacks complete whole-net physical connectivity evidence")
    if not intent.get("terminal_obligations",{}).get("complete"): errors.append("intent has unresolved physical terminal obligations")
    planning=intent.get("planning_evidence")
    if isinstance(planning,dict) and planning.get("obstacle_coverage",{}).get("live_snapshot") is False:
        review=planning.get("offline_obstacle_review") or {}
        if not (review.get("reviewed_live_target") is True and str(review.get("basis","")).strip()):
            errors.append("offline obstacle snapshot lacks a documented live-target reconciliation")
    return errors
def report(intent):
    lines=["# Analog routing intent report","",f"- Target: `{intent.get('target')}`",f"- Status: **{intent['decision']['status']}**",f"- Profile fingerprint: `{intent['sources'].get('profile_fingerprint')}`",f"- Routes / standalone vias / contact landings: {len(intent['routes'])} / {len(intent['vias'])} / {len(intent.get('contact_landings',[]))}",f"- Required physical pin islands covered: {intent.get('physical_access_coverage',{}).get('covered_count',0)}/{intent.get('physical_access_coverage',{}).get('required_count',0)}",f"- Whole-net physical connectivity: {'complete' if intent.get('physical_connectivity',{}).get('complete') else 'incomplete'}","","## Net metrics","","| Net | Length (um) | Routes | Vias | Contacts | Components | Off preferred direction |","|---|---:|---:|---:|---:|---:|---:|"]
    for n,m in sorted(intent["net_metrics"].items()): lines.append(f"| {n} | {m['path_length_um']:.6g} | {m['route_count']} | {m['via_count']} | {m.get('contact_landing_count',0)} | {m.get('connected_component_count','?')} | {m.get('off_preference_ratio',0):.1%} |")
    lines += ["","## Errors",""]+([f"- {x}" for x in intent["validation"]["errors"]] or ["- None"])+["","## Warnings",""]+[f"- {x}" for x in intent["validation"]["warnings"]]
    lines += ["","## Boundary","","Deterministic preflight only; original foundry DRC/LVS decks remain authoritative.",""]
    return "\n".join(lines)
def svg(intent):
    pts=([p for r in intent["routes"] for p in r["points_um"]]+[v["xy_um"] for v in intent["vias"]]
         +[c["xy_um"] for c in intent.get("contact_landings",[])]) or [[0,0],[1,1]]
    minx,maxx=min(p[0] for p in pts),max(p[0] for p in pts); miny,maxy=min(p[1] for p in pts),max(p[1] for p in pts); s=10.; pad=20.; w=max(100,(maxx-minx)*s+40); h=max(100,(maxy-miny)*s+40)
    cv={}; pal=["#2563eb","#dc2626","#16a34a","#9333ea","#ea580c","#0891b2"]
    def xy(p): return pad+(p[0]-minx)*s,h-pad-(p[1]-miny)*s
    intent_hash=digest(intent)
    body=[]
    for r in intent["routes"]:
        color=cv.setdefault(r["net"],pal[len(cv)%len(pal)]); points=" ".join(f"{xy(p)[0]:.2f},{xy(p)[1]:.2f}" for p in r["points_um"])
        attrs=(f'data-kind="route" data-object-id="{html.escape(r["id"],quote=True)}" '
               f'data-net="{html.escape(r["net"],quote=True)}" data-layer="{html.escape(r["layer"],quote=True)}" '
               f'data-purpose="{html.escape(r["purpose"],quote=True)}" data-width-um="{r["width_um"]:.12g}"')
        body.append(f'<polyline {attrs} points="{points}" fill="none" stroke="{color}" stroke-width="{max(2,r["width_um"]*s):.2f}"/>'); x,y=xy(r["points_um"][0]); body.append(f'<text x="{x+4}" y="{y-4}" font-size="10">{html.escape(r["net"])}</text>')
    for v in intent["vias"]:
        x,y=xy(v["xy_um"]); attrs=(f'data-kind="via" data-object-id="{html.escape(v["id"],quote=True)}" '
            f'data-net="{html.escape(v["net"],quote=True)}" data-via="{html.escape(v["via"],quote=True)}"')
        body.append(f'<rect {attrs} x="{x-3}" y="{y-3}" width="6" height="6" fill="#111827"/>')
    for c in intent.get("contact_landings",[]):
        x,y=xy(c["xy_um"]); attrs=(f'data-kind="contact" data-object-id="{html.escape(c["id"],quote=True)}" '
            f'data-net="{html.escape(c["net"],quote=True)}" data-via="{html.escape(c["via"],quote=True)}" '
            f'data-source-layer="{html.escape(c["source_layer"],quote=True)}"')
        body.append(f'<circle {attrs} cx="{x:.2f}" cy="{y:.2f}" r="2.5" fill="#f59e0b" stroke="#111827" stroke-width="0.8"/>')
    root_attrs=(f'data-schema="analog-layout-route.preview/v1" data-intent-sha256="{intent_hash}" '
        f'data-minx-um="{minx:.12g}" data-miny-um="{miny:.12g}" data-scale="{s:.12g}" '
        f'data-pad="{pad:.12g}" data-height="{h:.12g}"')
    return f'<svg xmlns="http://www.w3.org/2000/svg" {root_attrs} width="{w:.0f}" height="{h:.0f}" viewBox="0 0 {w} {h}"><rect width="100%" height="100%" fill="white"/>{"".join(body)}</svg>\n'
def main():
    ap=argparse.ArgumentParser(); subs=ap.add_subparsers(dest="cmd",required=True); b=subs.add_parser("build")
    for x in ("profile","terminal-access","spec","out","report"): b.add_argument("--"+x,required=True)
    b.add_argument("--preview"); v=subs.add_parser("validate"); v.add_argument("--profile",required=True); v.add_argument("--intent",required=True); a=ap.parse_args()
    if a.cmd=="build":
        out=build(load(a.profile),load(a.terminal_access),load(a.spec)); Path(a.out).write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf-8"); Path(a.report).write_text(report(out),encoding="utf-8")
        if a.preview: Path(a.preview).write_text(svg(out),encoding="utf-8")
        print(json.dumps({"status":out["decision"]["status"],"errors":len(out["validation"]["errors"]),"warnings":len(out["validation"]["warnings"]),"out":str(Path(a.out).resolve())})); return 0 if out["validation"]["valid"] else 2
    errors=validate(load(a.profile),load(a.intent)); print(json.dumps({"valid":not errors,"errors":errors})); return 0 if not errors else 2
if __name__=="__main__": raise SystemExit(main())
