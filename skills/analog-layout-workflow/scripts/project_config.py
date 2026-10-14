"""Project/PDK/circuit configuration binding. Pure data, no CAD writes."""
from pathlib import Path
import copy, hashlib, json, math, re

SCHEMA = 'analog-layout-workflow.project/v1'

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def load_project(path):
    path=Path(path).resolve(); project=read(path)
    if project.get('schema')!=SCHEMA: raise ValueError('Unsupported project schema')
    for field in ('source','target'):
        if set(project.get(field,{}))!={'lib','cell','view'} or not all(isinstance(v,str) and v for v in project[field].values()):
            raise ValueError('Explicit cellview required: '+field)
    if project['source']['view']!='schematic' or project['target']['view']!='layout':
        raise ValueError('Source schematic and target layout required')
    result=copy.deepcopy(project); bindings={}
    for name,schema in [('pdk','analog-layout-workflow.pdk-map/v1'),('circuit','analog-layout-workflow.circuit/v1'),('routing','analog-layout-workflow.routing-policy/v1')]:
        ref=project.get(name)
        if not isinstance(ref,str): raise ValueError('External configuration path required: '+name)
        file=(path.parent/ref).resolve(); data=read(file)
        if data.get('schema')!=schema: raise ValueError('Unsupported '+name+' schema')
        result[name]=data;bindings[name]={'path':str(file),'sha256':digest(data)}
    result['_base']=str(path.parent);result['_bindings']=bindings
    if project.get('site'):
        site_file=(path.parent/project['site']).resolve();site=read(site_file)
        if not all(isinstance(site.get(k),str) and site[k] for k in ('project_root','ic_root','calibre_root','technology_library')):
            raise ValueError('Incomplete external site profile')
        result['site']=site;bindings['site']={'path':str(site_file),'sha256':digest(site)}
    result['_project_sha256']=digest(project)
    for waiver in project.get('verification',{}).get('waivers',[]):
        if waiver.get('source')!='user' or not waiver.get('instruction','').strip() or not waiver.get('scope'):
            raise ValueError('Waiver requires project-specific user instruction and scope')
    if not result['pdk'].get('devices'): raise ValueError('Empty PDK device registry')
    return result

def numeric(value):
    if isinstance(value,bool): raise ValueError('Boolean is not a device dimension')
    m=re.fullmatch(r'\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([fpnuµμmkMG]?)\s*',str(value))
    if not m: raise ValueError('Unresolved numeric expression: '+str(value))
    result=float(m[1])*{'':1,'f':1e-15,'p':1e-12,'n':1e-9,'u':1e-6,'µ':1e-6,'μ':1e-6,'m':1e-3,'k':1e3,'M':1e6,'G':1e9}[m[2]]
    if not math.isfinite(result): raise ValueError('Nonfinite numeric parameter')
    return result

def normalize_schematic(schematic,pdk):
    """Names/units/types/masters from registry; unknown devices fail explicitly."""
    normalized=copy.deepcopy(schematic); normalized['instances']=[]; bindings={}
    for inst in schematic['instances']:
        choices=[d for d in pdk['devices'] if d['source_master']=={'lib':inst['lib'],'cell':inst['cell']}]
        if len(choices)!=1: raise ValueError('Unknown/ambiguous PDK master: '+inst['lib']+'/'+inst['cell'])
        device=choices[0]
        if device['kind']=='ignore': continue
        if device['kind'] not in ('nmos','pmos','capacitor','resistor'): raise ValueError('Unsupported device kind')
        item=copy.deepcopy(inst);item['kind']=device['kind'];item['params']={};entries=[]
        for canonical,rule in device['parameters'].items():
            source=rule.get('source',canonical); original=inst.get('params',{}).get(source,rule.get('default'))
            if original is None:
                if rule.get('required',False): raise ValueError('Missing parameter '+inst['name']+':'+source)
                continue
            item['params'][canonical]=original
            if not rule.get('target'): continue
            typ=rule['type']; value='1' if canonical=='m' else original
            if typ in ('float','int'):
                scale=numeric(rule.get('scale',1))
                if scale<=0: raise ValueError('Positive PCell unit scale required')
                value=numeric(value)*scale
                if not math.isfinite(value): raise ValueError('Nonfinite mapped PCell parameter')
                if typ=='int':
                    if value!=int(value): raise ValueError('Nonintegral parameter '+source)
                    value=int(value)
            elif typ=='string': value=str(value)
            else: raise ValueError('Unsupported PCell parameter type: '+str(typ))
            entries.append({'name':rule['target'],'type':typ,'value':value})
        item['params'].setdefault('m',1)
        for dimension in ('w','l','fw'):
            if dimension in item['params'] and numeric(item['params'][dimension])<=0:
                raise ValueError('Positive device dimension required: '+inst['name']+':'+dimension)
        if device['kind'] in ('nmos','pmos'):
            if 'fw' not in item['params'] and 'w' in item['params']:
                item['params']['fw']=numeric(item['params']['w'])/numeric(item['params'].get('fingers',item['params'].get('nf',1)))
        item['terms']={dest:inst.get('terms',{}).get(src) for dest,src in device['terminals'].items()}
        required=('D','G','S','B') if device['kind'] in ('nmos','pmos') else ('N1','N2')
        if any(not item['terms'].get(t) for t in required): raise ValueError('Incomplete electrical terminals: '+inst['name'])
        if len({e['name'] for e in entries})!=len(entries): raise ValueError('Duplicate PCell parameter binding')
        bindings[inst['name']]={'master':device['target_master'],'entries':entries,'source_parameters':copy.deepcopy(inst.get('params',{}))}
        normalized['instances'].append(item)
    return normalized,bindings

def typed_params(instance,quote):
    """Convert mapped entries to SKILL. None selects the legacy importer contract."""
    entries=instance.get('pcell_parameter_entries')
    if entries is None: return None
    parts=[];seen=set()
    for e in entries:
        if e['name'] in seen: raise ValueError('Duplicate mapped parameter')
        seen.add(e['name']); typ=e['type'];value=e['value']
        if typ=='string': encoded=quote(str(value))
        elif typ in ('float','int'):
            value=numeric(value)
            if typ=='int' and value!=int(value): raise ValueError('Nonintegral mapped parameter')
            encoded=format(value,'.12g')
        else: raise ValueError('Unsupported mapped parameter type')
        parts.append('list('+quote(e['name'])+' '+quote(typ)+' '+encoded+')')
    return 'list('+' '.join(parts)+')'

def configured_groups(copies,modules):
    """Explicit logical rows consume every m-copy once; no truncation or name rules."""
    by={c['name']:c for c in copies};logical={}
    for c in copies: logical.setdefault(c['logical_device'],[]).append(c['name'])
    used=set();groups=[];associations=[];module_names=set();logical_owners={}
    for module in modules:
        name=module['name']
        if name in module_names: raise ValueError('Duplicate module name')
        module_names.add(name);rows=[];dummies=module.get('dummies',[])
        for tokens in module['rows']:
            if not tokens: raise ValueError('Empty placement row')
            row=[]
            for token in tokens:
                available=[n for n in logical.get(token,[]) if n not in used]
                choice=token if token in by else available[0] if available else None
                if choice is None or choice in used: raise ValueError('Missing/duplicate copy in rows: '+token)
                used.add(choice);row.append(choice);by[choice]['group']=name
            rows.append(row)
        members={by[n]['logical_device'] for row in rows for n in row}
        for logical_device in members:
            if logical_device in logical_owners: raise ValueError('Logical device split across module ownership')
            logical_owners[logical_device]=name
        if module.get('pattern') not in (None,'ABBA','BAAB'): raise ValueError('Unsupported declared matching pattern')
        if not set(dummies)<=members: raise ValueError('Dummy absent from module rows')
        active=sorted(members-set(dummies));mapping={n:by[n]['align_instance'] for row in rows for n in row}
        if not active: raise ValueError('Configured module requires an active device')
        groups.append({'name':name,'kind':'configured_module','role':module.get('role','device_array'),
            'logical_devices':active,'matching_mode':module.get('matching','common_axis'),
            'pattern_mode':'configured_rows','rows':rows,'align_rows':[[mapping[n] for n in row] for row in rows],
            'instances':list(mapping.values()),'constraints':[],
            'dummy_logical_devices':dummies,'dummy_copies':[],
            'configured_dummy_copies':[n for row in rows for n in row if by[n]['logical_device'] in dummies],
            'required_active_pattern':module.get('pattern'),
            'configured_orientations':module.get('orientations',{})})
        if set(module.get('orientations',{}))-{n for row in rows for n in row}:
            raise ValueError('Orientation override references a copy outside its module')
        for dummy in dummies:
            associations.append({'dummy_logical_device':dummy,'target_group':name,
                'status':'associated_project_configuration','dummy_copies':logical[dummy]})
    if used!=set(by): raise ValueError('Incomplete module coverage: '+str(sorted(set(by)-used)))
    return groups,associations

def position_macros(macros,policy,snap,grid,default_gap):
    """Configured stack, rows or explicit placements; no circuit role ordering."""
    if not math.isfinite(grid) or grid<=0 or not math.isfinite(default_gap) or default_gap<0:
        raise ValueError('Positive grid and nonnegative macro gap required')
    names={m['name'] for m in macros};order=policy.get('order')
    if not isinstance(order,list) or set(order)!=names or len(order)!=len(names):
        raise ValueError('Floorplan order must list every module exactly once')
    by={m['name']:m for m in macros};macros[:]=[by[n] for n in order]
    mode=policy.get('mode','stack');axis=snap(policy.get('axis_x_um',max(m['size'][0] for m in macros)/2),grid)
    origins={};x=float(policy.get('origin_um',[0,0])[0]);y=float(policy.get('origin_um',[0,0])[1])
    if mode=='explicit':
        origins=policy['origins_um']
        if set(origins)!=names: raise ValueError('Explicit origins require complete module coverage')
    elif mode=='stack':
        for index,m in enumerate(macros):
            origins[m['name']]=[axis-m['size'][0]/2,y]
            gap=policy.get('gap_after_um',{}).get(m['name'],default_gap)
            if not math.isfinite(gap) or gap<0: raise ValueError('Invalid macro gap')
            y+=m['size'][1]+gap
    elif mode=='rows':
        rows=policy['rows'];flat=[n for row in rows for n in row]
        if set(flat)!=names or len(flat)!=len(names) or any(not row for row in rows): raise ValueError('Invalid floorplan rows')
        for row in rows:
            cursor=x;height=max(by[n]['size'][1] for n in row)
            for n in row:
                origins[n]=[cursor,y];cursor+=by[n]['size'][0]+default_gap
            y+=height+default_gap
    else: raise ValueError('Unsupported floorplan mode: '+str(mode))
    for n,xy in origins.items():
        if len(xy)!=2 or any(not math.isfinite(v) or abs(v/grid-round(v/grid))>1e-6 for v in xy):
            raise ValueError('Configured module origin is not on manufacturing grid: '+n)
    return origins,axis
