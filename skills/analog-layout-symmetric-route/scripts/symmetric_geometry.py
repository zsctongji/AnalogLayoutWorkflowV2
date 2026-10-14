"""Sourced rectangular geometry for strict joint routing; no foundry signoff."""
import math

EPS = 1e-10

class SolverError(ValueError):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code

def number(value, label, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SolverError('INVALID_INPUT', label+' must be a finite number')
    if value < 0 or (positive and value == 0):
        raise SolverError('INVALID_INPUT', label+' must be '+('positive' if positive else 'nonnegative'))
    return float(value)

def box_ok(box):
    return (isinstance(box, list) and len(box)==2 and all(isinstance(p,list) and len(p)==2 for p in box)
            and all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for p in box for v in p)
            and all(box[1][k]>box[0][k] for k in (0,1)))

def overlap(a,b):
    return all(max(a[0][k],b[0][k]) < min(a[1][k],b[1][k])-EPS for k in (0,1))

def gap(a,b,metric='euclidean'):
    delta=[max(a[0][k]-b[1][k],b[0][k]-a[1][k],0) for k in (0,1)]
    if metric=='euclidean':return math.hypot(*delta)
    if metric=='max_axis':return max(delta)
    raise SolverError('UNSUPPORTED_RULE','Unsupported spacing metric '+str(metric))

def contains(outer,inner):
    return all(outer[0][k]-EPS<=inner[0][k] and inner[1][k]<=outer[1][k]+EPS for k in (0,1))

def reflected(point,axis):
    result=list(point);k=0 if axis['coordinate']=='x' else 1
    result[k]=round(2*axis['value_um']-result[k],12)
    return result

def reflected_box(box,axis):
    pts=[reflected(p,axis) for p in box]
    return [[min(p[k] for p in pts) for k in (0,1)],[max(p[k] for p in pts) for k in (0,1)]]

def segment_box(a,b,width):
    if tuple(a[:2])==tuple(b[:2]) or (a[0]!=b[0] and a[1]!=b[1]):
        raise SolverError('NON_MANHATTAN','Expected a nonzero orthogonal segment')
    return [[min(a[k],b[k])-width/2 for k in (0,1)],
            [max(a[k],b[k])+width/2 for k in (0,1)]]

def wire(a,b,width,net,ident='search'):
    return {'id':ident,'kind':'metal','layer':a[2],'net':net,'bbox_um':segment_box(a,b,width)}

def via_objects(via,xy,net,ident='search-via'):
    g=via['geometry'];cut=g['cut_size_um'];pitch=g.get('cut_spacing_um',[0,0])
    rows,cols=g.get('rows',1),g.get('columns',1)
    if any(isinstance(v,bool) or not isinstance(v,int) or v<1 for v in (rows,cols)):
        raise SolverError('UNSUPPORTED_VIA','Via array rows/columns must be positive integers')
    for key in ('cut_size_um','cut_spacing_um','layer1_enclosure_um','layer2_enclosure_um'):
        values=g.get(key,[0,0] if key=='cut_spacing_um' else None)
        if not isinstance(values,list) or len(values)!=2:raise SolverError('UNSUPPORTED_VIA','Incomplete '+key)
        for value in values:number(value,key,key=='cut_size_um')
    if set(g)-{'cut_layer','cut_size_um','cut_spacing_um','rows','columns','layer1_enclosure_um','layer2_enclosure_um'}:
        raise SolverError('UNSUPPORTED_VIA','Offsets/orientations require a separately qualified geometry adapter')
    total=[cols*cut[0]+(cols-1)*pitch[0],rows*cut[1]+(rows-1)*pitch[1]]
    result=[]
    for layer,key in ((via['lower'],'layer1_enclosure_um'),(via['upper'],'layer2_enclosure_um')):
        half=[total[k]/2+g[key][k] for k in (0,1)]
        result.append({'id':ident+'/'+layer,'kind':'metal','layer':layer,'net':net,
                       'bbox_um':[[xy[k]-half[k] for k in (0,1)],[xy[k]+half[k] for k in (0,1)]]})
    for row in range(rows):
        for col in range(cols):
            center=[xy[0]-total[0]/2+cut[0]/2+col*(cut[0]+pitch[0]),
                    xy[1]-total[1]/2+cut[1]/2+row*(cut[1]+pitch[1])]
            result.append({'id':ident+'/cut/'+str(row)+'/'+str(col),'via_instance':ident,'kind':'cut',
                'layer':g['cut_layer'],'net':net,'bbox_um':[[center[k]-cut[k]/2 for k in (0,1)],
                                                      [center[k]+cut[k]/2 for k in (0,1)]]})
    return result

def derive_levels(profile,explicit=None):
    functions=[f for f in profile.get('layer_functions',[]) if f.get('function')=='metal']
    functions.sort(key=lambda f:f.get('rank') if isinstance(f.get('rank'),(int,float)) else math.inf)
    ranks=[f.get('rank') for f in functions]
    if functions and (any(isinstance(r,bool) or not isinstance(r,(int,float)) or not math.isfinite(r) for r in ranks) or len(set(ranks))!=len(ranks)):
        raise SolverError('METAL_LEVELS_UNKNOWN','Metal stack ranks are incomplete or ambiguous')
    derived={f['layer']:i+1 for i,f in enumerate(functions)}
    levels=explicit or derived
    used={r['layer'] for r in profile['routing_layers']}
    if not used<=set(levels):raise SolverError('METAL_LEVELS_UNKNOWN','Actual metal levels are required for all routing layers')
    for layer,level in levels.items():
        if isinstance(level,bool) or not isinstance(level,int) or level<1:
            raise SolverError('INVALID_INPUT','Metal levels must be positive integers')
        if layer in derived and level!=derived[layer]:raise SolverError('METAL_LEVEL_CONFLICT','Explicit stack disagrees with PDK rank: '+layer)
    if len(set(levels.values()))!=len(levels):raise SolverError('METAL_LEVEL_CONFLICT','Duplicate metal levels')
    return levels

class Geometry:
    def __init__(self,planner,profile,obstacles,request):
        self.p=planner;self.profile=profile;self.grid=profile['manufacturing_grid_um']
        number(self.grid,'manufacturing grid',True)
        self.bounds=obstacles['bounds_um']
        if not box_ok(self.bounds):raise SolverError('INVALID_INPUT','Invalid routing bounds')
        self.levels=derive_levels(profile,request.get('metal_levels'))
        self.directions={layer:'vertical' if level%2 else 'horizontal' for layer,level in self.levels.items()}
        self.minimum={};self.spacings={};self.metrics={}
        for rule in profile['routing_layers']:
            layer=rule['layer']
            self.minimum[layer]=planner.unconditional_floor(rule['minimum_width_rules'],'minimum width')
            self.spacings[layer]=planner.unconditional_floor(rule['minimum_spacing_rules'],'minimum spacing')
            number(self.minimum[layer],'minimum width',True);number(self.spacings[layer],'minimum spacing')
            self.metrics[layer]='euclidean'
            for conditional in rule.get('width_spacing_rules',[]):
                if not conditional.get('source'):raise SolverError('RULES_UNKNOWN','Width-spacing rule source missing')
                self.spacings[layer]=max(self.spacings[layer],number(conditional['spacing_um'],'conditional spacing'))
            preferred=rule.get('preferred_direction')
            if preferred and preferred not in ('none',self.directions[layer]):
                raise SolverError('PDK_DIRECTION_CONFLICT','PDK direction disagrees with odd/even policy: '+layer)
        self.vias={v['name']:v for v in planner.via_catalog(profile)}
        self.cut_rules=request.get('cut_rules',{})
        self.cross_rules={}
        for layer,rule in self.cut_rules.items():
            if not rule.get('source'):raise SolverError('RULES_UNKNOWN','Cut spacing source missing: '+layer)
            number(rule['spacing_um'],'cut spacing');gap([[0,0],[1,1]],[[2,2],[3,3]],rule.get('metric','euclidean'))
        for rule in request.get('cross_cut_rules',[]):
            layers=rule.get('layers',[])
            if len(layers)!=2 or len(set(layers))!=2 or not rule.get('source'):
                raise SolverError('RULES_UNKNOWN','Cross-cut rule needs two layers and provenance')
            number(rule['spacing_um'],'cross-cut spacing');key=frozenset(layers)
            if key in self.cross_rules:raise SolverError('INVALID_INPUT','Duplicate cross-cut rule')
            self.cross_rules[key]=rule
        self.local=request.get('local_access',{})
        cut_layers=set(self.cut_rules)|{v['geometry']['cut_layer'] for v in self.vias.values()}
        self.obstacles=[];self.soft=[]
        for raw in obstacles.get('obstacles',[]):
            if not box_ok(raw.get('bbox_um')):raise SolverError('INVALID_INPUT','Invalid obstacle box')
            if raw.get('hard',True) is False:
                if not raw.get('source'):raise SolverError('INVALID_INPUT','Soft obstacle requires sourced cost')
                number(raw.get('cost_per_um'),'soft obstacle cost');self.soft.append(raw)
                continue
            kind=raw.get('kind','cut' if raw['layer'] in cut_layers else 'metal')
            if kind not in ('metal','cut','rect'):raise SolverError('UNSUPPORTED_GEOMETRY','Conservative rectangle obstacle required')
            self.obstacles.append({**raw,'kind':'metal' if kind=='rect' else kind})
        self.via_evidence=request.get('via_mirror_evidence',{})
        self.rejected={};self.checked=0

    def reject(self,code):
        self.rejected[code]=self.rejected.get(code,0)+1
        return False

    def spacing(self,a,b):
        if a['kind']=='cut' and b['kind']=='cut':
            if a['layer']==b['layer']:
                rule=self.cut_rules.get(a['layer'])
                if not rule:raise SolverError('RULES_UNKNOWN','Cut rule missing: '+a['layer'])
                return rule['spacing_um'],rule.get('metric','euclidean'),False
            rule=self.cross_rules.get(frozenset((a['layer'],b['layer'])))
            if not rule:raise SolverError('RULES_UNKNOWN','Cross-cut/stacking rule missing: '+a['layer']+'/'+b['layer'])
            allowed=(rule.get('stacking_allowed') is True and a.get('net') and a.get('net')==b.get('net')
                     and all(abs(sum(a['bbox_um'][j][k] for j in (0,1))-sum(b['bbox_um'][j][k] for j in (0,1)))<EPS for k in (0,1)))
            return rule['spacing_um'],rule.get('metric','euclidean'),allowed
        if a['layer']!=b['layer']:return None
        if a['kind']=='metal' and b['kind']=='metal' and a.get('net') and a.get('net')==b.get('net'):return None
        if a['kind']!=b['kind']:raise SolverError('UNSUPPORTED_GEOMETRY','Layer kind conflict: '+a['layer'])
        if a['layer'] not in self.spacings:raise SolverError('RULES_UNKNOWN','Metal spacing missing: '+a['layer'])
        return self.spacings[a['layer']],'euclidean',False

    def compatible(self,a,b):
        if (a['kind']=='cut' and b['kind']=='cut' and a['layer']==b['layer'] and a.get('net') and a.get('net')==b.get('net')
            and a.get('via_instance') and a.get('via_instance')==b.get('via_instance') and a['bbox_um']==b['bbox_um']):return True
        rule=self.spacing(a,b)
        if rule is None:return True
        required,metric,stack=rule
        if stack:return True
        return not overlap(a['bbox_um'],b['bbox_um']) and gap(a['bbox_um'],b['bbox_um'],metric)+EPS>=required

    def clear(self,objects,reserved=()):
        self.checked+=1
        for i,obj in enumerate(objects):
            if not contains(self.bounds,obj['bbox_um']):return self.reject('BOUNDS')
            for other in self.obstacles+list(reserved)+objects[:i]:
                if not self.compatible(obj,other):return self.reject('GEOMETRY_CONFLICT')
        return True

    def qualified_via(self,name,widths,axis=None):
        via=self.vias[name];objects=via_objects(via,[0,0],'test',name)
        cut_layer=via['geometry']['cut_layer']
        if cut_layer not in self.cut_rules:raise SolverError('RULES_UNKNOWN','Cut spacing not supplied for '+name)
        evidence=self.via_evidence.get(name,{})
        if axis and (evidence.get('geometry_sha256')!=self.p.ROUTE.digest(via['geometry'])
                     or not evidence.get('source') or evidence.get('mirror_verified') is not True):
            raise SolverError('VIA_MIRROR_UNKNOWN','Current normalized via mirror qualification required: '+name)
        if axis:
            signature=lambda box:tuple(tuple(round(v,12) for v in p) for p in box)
            boxes={(o['layer'],signature(o['bbox_um'])) for o in objects}
            center_axis={**axis,'value_um':0}
            if any((o['layer'],signature(reflected_box(o['bbox_um'],center_axis))) not in boxes for o in objects):
                raise SolverError('VIA_NOT_MIRRORABLE','Actual normalized via array is not mirror invariant')
        for obj in objects:
            if obj['kind']!='metal':continue
            layer=obj['layer'];k=0 if self.directions[layer]=='vertical' else 1
            if widths[layer]+EPS<obj['bbox_um'][1][k]-obj['bbox_um'][0][k]:return False
        # Same-via array cut spacing is checked too.
        for i,obj in enumerate(objects):
            for other in objects[:i]:
                if not self.compatible(obj,other):raise SolverError('ILLEGAL_VIA_ARRAY','Qualified cut spacing violated inside '+name)
        return True

    def local_edge(self,a,b,net,islands,width=0.0000000001):
        if self.levels[a[2]]!=1:return True
        relevant=[self.local.get(i,{}) for i in islands]
        if not relevant or any(not r.get('source') or not box_ok(r.get('region_um')) or 'max_length_um' not in r for r in relevant):
            raise SolverError('LOCAL_ACCESS_UNKNOWN','Every M1 island needs a sourced local region and cumulative budget')
        for r in relevant:number(r['max_length_um'],'M1 cumulative budget',True)
        box=segment_box(a,b,width)
        if not any(contains(r['region_um'],box) for r in relevant):return self.reject('M1_REGION')
        return True

    def soft_cost(self,a,b,layer):
        d=1 if a[0]==b[0] else 0;fixed=1-d;cost=0
        for region in self.soft:
            box=region['bbox_um']
            if region['layer']==layer and box[0][fixed]<=a[fixed]<=box[1][fixed]:
                length=max(0,min(max(a[d],b[d]),box[1][d])-max(min(a[d],b[d]),box[0][d]))
                cost+=length*region['cost_per_um']
        return cost

def union_contains(box,boxes):
    """Exact rectangle-union coverage, not bbox-union containment."""
    xs=sorted({box[0][0],box[1][0],*(max(box[0][0],min(box[1][0],p[0])) for b in boxes for p in b)})
    ys=sorted({box[0][1],box[1][1],*(max(box[0][1],min(box[1][1],p[1])) for b in boxes for p in b)})
    for x0,x1 in zip(xs,xs[1:]):
        for y0,y1 in zip(ys,ys[1:]):
            if x1-x0<=EPS or y1-y0<=EPS:continue
            x,y=(x0+x1)/2,(y0+y1)/2
            if not any(b[0][0]-EPS<=x<=b[1][0]+EPS and b[0][1]-EPS<=y<=b[1][1]+EPS for b in boxes):return False
    return True
