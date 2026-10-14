"""Joint A* over legal reflected actions, with hard layer directions."""
import heapq, math
from symmetric_geometry import SolverError, EPS, number, reflected, wire, via_objects, segment_box

class Budget:
    def __init__(self,settings):
        allowed={'max_expansions','max_coordinates','max_vias_per_path','access_combinations','group_candidates',
                 'beam_width','max_orderings','top_k'}
        if set(settings)-allowed:raise SolverError('INVALID_INPUT','Unknown strict search settings')
        defaults={'max_expansions':30000,'max_coordinates':160,'max_vias_per_path':12,
                  'access_combinations':12,'group_candidates':3,'beam_width':4,'max_orderings':8,'top_k':3}
        self.limits={**defaults,**settings};self.expansions=0;self.searches=0;self.truncated=False
        for key,value in self.limits.items():
            if isinstance(value,bool) or not isinstance(value,int) or value<1:
                raise SolverError('INVALID_INPUT','Positive integer search budget required: '+key)
    def tick(self):
        self.expansions+=1
        if self.expansions>self.limits['max_expansions']:
            raise SolverError('BUDGET_EXHAUSTED','Joint A* expansion budget exhausted')

class JointGraph:
    def __init__(self,geometry,first,second,axis,reserved,island_ids,budget,costs=None,side=None):
        self.g=geometry;self.first=first;self.second=second;self.axis=axis
        self.reserved=list(reserved);self.islands=island_ids;self.budget=budget;self.side=side
        self.layers=first['layers'];self.widths=first['widths_um'];self.costs=costs or {}
        for key in self.costs:number(self.costs[key],key)
        if set(self.costs)-{'via_cost_um','bend_cost_um','metal_area_weight'}:
            raise SolverError('INVALID_INPUT','Unsupported strict routing cost')
        self.vias={}
        for name,via in geometry.vias.items():
            if via['lower'] in self.layers and via['upper'] in self.layers:
                if abs(geometry.levels[via['lower']]-geometry.levels[via['upper']])!=1:continue
                if geometry.qualified_via(name,self.widths,axis):self.vias[name]=via
        if second:
            if second['layers']!=first['layers'] or second['widths_um']!=first['widths_um']:
                raise SolverError('PAIR_POLICY_MISMATCH','Strict pair requires identical allowed layers and widths')
        self.rejected=set();self.via_cache={};self.forbidden=set()

    def transform(self,node):return tuple(reflected(node,self.axis))

    def node_allowed(self,node):
        g=self.g;k=0 if self.axis and self.axis['coordinate']=='x' else 1
        if self.side is not None and self.side*(node[k]-self.axis['value_um']) < -EPS:return False
        return all(g.bounds[0][d]-EPS<=node[d]<=g.bounds[1][d]+EPS for d in (0,1))

    def wire_actions(self,a,b):
        objects=[wire(a,b,self.widths[a[2]],self.first['net'])]
        if self.second:
            ta,tb=self.transform(a),self.transform(b)
            mirror=wire(ta,tb,self.widths[a[2]],self.second['net'])
            if mirror['bbox_um']!=objects[0]['bbox_um'] or mirror['net']!=objects[0]['net']:objects.append(mirror)
        return objects

    def via_actions(self,node,name):
        cache=(name,node[0],node[1])
        if cache in self.via_cache:return self.via_cache[cache]
        via=self.vias[name];result=[]
        placements=[(self.first['net'],node)]
        if self.second:placements.append((self.second['net'],self.transform(node)))
        seen=set()
        for net,point in placements:
            key=(net,name,point[0],point[1])
            if key in seen:continue
            seen.add(key);ident='|'.join(map(str,key));objects=via_objects(via,point[:2],net,ident)
            result.extend(objects)
        # Choose one common legal direction for the minimal real landing conductor.
        canonical=via_objects(via,node[:2],self.first['net'],'canonical')
        for obj in canonical:
            if obj['kind']!='metal':continue
            layer=obj['layer'];d=1 if self.g.directions[layer]=='vertical' else 0
            half=max(abs(obj['bbox_um'][0][d]-node[d]),abs(obj['bbox_um'][1][d]-node[d]))
            half=self.g.p.snap_up(max(0,half-self.widths[layer]/2),self.g.grid)
            choices=[]
            if half>EPS:
                a=list(node[:2])+[layer];b=list(a);a[d]-=half;b[d]+=half;choices.append((a,b))
            else:
                for sign in (-1,1):
                    a=list(node[:2])+[layer];b=list(a);b[d]+=sign*self.g.grid;choices.append((a,b))
            selected=None
            for a,b in choices:
                additions=[];used=set()
                for placement_index,(net,point) in enumerate(placements):
                    aa,bb=(a,b) if placement_index==0 else (self.transform(a),self.transform(b))
                    marker=(net,tuple(sorted((tuple(aa),tuple(bb)))))
                    if marker in used:continue
                    used.add(marker)
                    additions.append(wire(aa,bb,self.widths[layer],net,'|'.join(map(str,(net,name,point[0],point[1])))+'/landing-wire/'+layer))
                if self.g.clear(result+additions,self.reserved):selected=additions;break
            # Returning a colliding choice lets the ordinary action gate reject it.
            result.extend(selected if selected is not None else additions)
        self.via_cache[cache]=result
        return result

    def clear_wire(self,a,b,history=()):
        direction='vertical' if a[0]==b[0] else 'horizontal'
        if direction!=self.g.directions[a[2]]:return self.g.reject('HARD_DIRECTION')
        if not self.node_allowed(b):return self.g.reject('HALF_PLANE')
        if not self.g.local_edge(a,b,self.first['net'],self.islands[0],self.widths[a[2]]):return False
        if self.second and not self.g.local_edge(self.transform(a),self.transform(b),self.second['net'],self.islands[1],self.widths[a[2]]):return False
        return self.g.clear(self.wire_actions(a,b),self.reserved+list(history))

    def coordinates(self,start,goals,extras):
        g=self.g;p=g.p;grid=g.grid
        xs={start[0],p.snap_up(g.bounds[0][0],grid),p.snap_down(g.bounds[1][0],grid)}
        ys={start[1],p.snap_up(g.bounds[0][1],grid),p.snap_down(g.bounds[1][1],grid)}
        for point in list(goals)+list(extras):xs.add(point[0]);ys.add(point[1])
        if self.axis:
            k=0 if self.axis['coordinate']=='x' else 1
            (xs if k==0 else ys).add(self.axis['value_um'])
        widths=max(self.widths.values())/2
        via_half=max((max(abs(v) for obj in via_objects(v,[0,0],'coordinate') for pt in obj['bbox_um'] for v in pt)
                      for v in self.vias.values()),default=0)
        spacing=max([*g.spacings.values(),*(r['spacing_um'] for r in g.cut_rules.values()),
                     *(r['spacing_um'] for r in g.cross_rules.values())],default=0)
        margin=max(widths,via_half)+spacing+grid
        xs.update((p.snap_up(g.bounds[0][0]+margin,grid),p.snap_down(g.bounds[1][0]-margin,grid)))
        ys.update((p.snap_up(g.bounds[0][1]+margin,grid),p.snap_down(g.bounds[1][1]-margin,grid)))
        for point in [start,*goals,*extras]:
            xs.update((p.snap_down(point[0]-margin,grid),p.snap_up(point[0]+margin,grid)))
            ys.update((p.snap_down(point[1]-margin,grid),p.snap_up(point[1]+margin,grid)))
        for obj in g.obstacles+g.soft+self.reserved:
            if obj['layer'] not in self.layers and obj['kind']!='cut':continue
            boxes=[obj['bbox_um']]
            if self.second:boxes.append([reflected(pt,self.axis) for pt in obj['bbox_um']])
            for box in boxes:
                low=[min(pt[k] for pt in box) for k in (0,1)];high=[max(pt[k] for pt in box) for k in (0,1)]
                xs.update((p.snap_down(low[0]-margin,grid),p.snap_up(high[0]+margin,grid)))
                ys.update((p.snap_down(low[1]-margin,grid),p.snap_up(high[1]+margin,grid)))
        for ids in self.islands:
            for ident in ids:
                rule=g.local.get(ident)
                if rule:
                    for pt in rule['region_um']:xs.add(p.snap(pt[0],grid));ys.add(p.snap(pt[1],grid))
        xs=sorted(v for v in xs if g.bounds[0][0]-EPS<=v<=g.bounds[1][0]+EPS)
        ys=sorted(v for v in ys if g.bounds[0][1]-EPS<=v<=g.bounds[1][1]+EPS)
        if len(xs)>self.budget.limits['max_coordinates'] or len(ys)>self.budget.limits['max_coordinates']:
            raise SolverError('BUDGET_EXHAUSTED','Visibility coordinate budget exhausted')
        # Axis itself may be half-grid; it is a wire node only if on-grid.
        return [v for v in xs if abs(v/grid-round(v/grid))<1e-6], [v for v in ys if abs(v/grid-round(v/grid))<1e-6]

    def search(self,start,goals,extras=(),forbidden=(),starts=None):
        self.budget.searches+=1;goals={tuple(g) for g in goals};start=tuple(start)
        starts=sorted({tuple(p) for p in (starts or [start]) if self.node_allowed(p)})
        goals={g for g in goals if self.node_allowed(g)}
        if not goals or not starts:return None
        xs,ys=self.coordinates(starts[0],goals,[*extras,*starts]);xi={x:i for i,x in enumerate(xs)};yi={y:i for i,y in enumerate(ys)}
        starts=[p for p in starts if p[0] in xi and p[1] in yi]
        if not starts:return None
        via_adjacency={layer:[] for layer in self.layers}
        for name,via in sorted(self.vias.items()):
            via_adjacency[via['lower']].append((via['upper'],name));via_adjacency[via['upper']].append((via['lower'],name))
        # Via history belongs to the state: cut/stack legality cannot be reduced to position alone.
        initials={(p,'',(),0.0) for p in starts};distance={p:0.0 for p in initials};parent={};actions={};queue=[];serial=0
        heuristic=lambda n:min(abs(n[0]-g[0])+abs(n[1]-g[1]) for g in goals)
        for initial in sorted(initials):
            heapq.heappush(queue,(heuristic(initial[0]),0.0,serial,initial));serial+=1
        forbidden=set(forbidden)|self.forbidden
        while queue:
            _,cost,_,state=heapq.heappop(queue)
            if cost!=distance.get(state):continue
            self.budget.tick();node,incoming,vhistory,m1run=state;x,y,layer=node
            if node in goals:
                result=[]
                while state not in initials:
                    result.append(actions[state]);state=parent[state]
                return list(reversed(result)),cost
            history=[o for h in vhistory for o in self.via_actions((h[0],h[1],h[2]),h[3])]
            neighbors=[];d=1 if self.g.directions[layer]=='vertical' else 0
            axis_values=ys if d else xs;index=yi[y] if d else xi[x]
            for j in (index-1,index+1):
                if 0<=j<len(axis_values):
                    nxt=list(node);nxt[d]=axis_values[j];nxt=tuple(nxt)
                    if frozenset((node,nxt)) in forbidden:continue
                    if self.clear_wire(node,nxt,history):neighbors.append((nxt,'wire',None))
            if len(vhistory)<self.budget.limits['max_vias_per_path']:
                for other,name in via_adjacency[layer]:
                    nxt=(x,y,other);signature=(x,y,layer,name)
                    if frozenset((node,nxt)) in forbidden:continue
                    if any(h[0]==x and h[1]==y and h[3]==name for h in vhistory):continue
                    objects=self.via_actions(node,name)
                    if not self.node_allowed(nxt):continue
                    local_ok=True
                    for obj in objects:
                        if obj['kind']=='metal' and self.g.levels[obj['layer']]==1:
                            ids=self.islands[0] if obj['net']==self.first['net'] else self.islands[1]
                            rules=[self.g.local.get(i,{}) for i in ids]
                            from symmetric_geometry import contains
                            if not any(r.get('source') and contains(r.get('region_um',[[0,0],[0,0]]),obj['bbox_um']) for r in rules):
                                local_ok=False;self.g.reject('M1_VIA_REGION');break
                    if not local_ok:continue
                    if self.g.clear(objects,self.reserved+history):neighbors.append((nxt,'via',name))
            for nxt,kind,name in neighbors:
                length=abs(nxt[0]-x)+abs(nxt[1]-y);direction=self.g.directions[layer] if kind=='wire' else incoming
                run=round(m1run+length,12) if kind=='wire' and self.g.levels[layer]==1 else 0.0
                if kind=='wire' and self.g.levels[layer]==1:
                    limits=[number(self.g.local[i]['max_length_um'],'M1 budget') for ids in self.islands for i in ids if i in self.g.local]
                    if not limits or run>max(limits)+EPS:self.g.reject('M1_LENGTH');continue
                new_history=vhistory+((x,y,layer,name),) if kind=='via' else vhistory
                # Prevent loops at identical layered nodes along this candidate path.
                ancestor=state;loop=False
                while True:
                    if ancestor[0]==nxt:loop=True;break
                    if ancestor in initials:break
                    ancestor=parent[ancestor]
                if loop:continue
                factor=2 if self.second else 1
                delta=factor*(length*(1+self.costs.get('metal_area_weight',0)*self.widths[layer])
                    + (self.costs.get('via_cost_um',2) if kind=='via' else 0)
                    + (self.costs.get('bend_cost_um',self.g.grid) if kind=='wire' and incoming and incoming!=direction else 0))
                if kind=='wire':
                    delta+=self.g.soft_cost(node,nxt,layer)
                    if self.second:delta+=self.g.soft_cost(self.transform(node),self.transform(nxt),layer)
                new=(nxt,direction,new_history,run);nc=cost+delta
                if nc+EPS<distance.get(new,math.inf):
                    distance[new]=nc;parent[new]=state;actions[new]={'a':node,'b':nxt,'kind':kind,'via':name}
                    serial+=1;heapq.heappush(queue,(nc+heuristic(nxt),nc,serial,new))
        return None

def nodes_on_tree(paths,point,initial):
    result=set(initial)
    for action in paths:
        a,b=action['a'],action['b'];result.update((a,b))
        if action['kind']=='wire':
            if a[0]==b[0]:result.add((a[0],min(max(point[1],min(a[1],b[1])),max(a[1],b[1])),a[2]))
            else:result.add((min(max(point[0],min(a[0],b[0])),max(a[0],b[0])),a[1],a[2]))
    return result

def grow_tree(graph,nodes,variant=0):
    """Connect all representative islands to a shared tree; reflection stays coupled."""
    paths=[];cost=0;reached={nodes[0]};remaining=list(nodes[1:]);extras=list(nodes)
    while remaining:
        choices=[]
        # Evaluate each frontier endpoint, rather than declaring failure on its first access.
        for i,node in enumerate(remaining):
            goals=nodes_on_tree(paths,node,reached)
            found=graph.search(node,goals,extras)
            if found:
                actions,value=found;choices.append((value,i,actions))
        if not choices:raise SolverError('NO_PATH_IN_GRAPH','No joint legal path connects the next terminal in the finite graph')
        choices.sort(key=lambda c:(c[0],c[1]));value,index,selected=choices[min(variant,len(choices)-1)]
        cost+=value;paths.extend(selected);reached.add(remaining.pop(index))
        # Reserve both trees incrementally, including every cut and landing.
        for action in selected:
            graph.reserved.extend(graph.wire_actions(action['a'],action['b']) if action['kind']=='wire'
                                  else graph.via_actions(action['a'],action['via']))
    return paths,cost
