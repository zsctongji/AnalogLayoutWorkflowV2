"""Consolidated review evidence for offline joint solver runs."""
from pathlib import Path
import json
from symmetric_geometry import derive_levels

def write(path,value):
    Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')

def context(out,profile,access,obstacles,request,result,planner):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    sources={'profile_fingerprint':profile.get('fingerprint',{}).get('value'),
             'terminal_access_sha256':planner.ROUTE.digest(access),'obstacles_sha256':planner.ROUTE.digest(obstacles),
             'request_sha256':planner.ROUTE.digest(request)}
    write(out/'input-audit.json',{'schema':'analog-layout-symmetric-route.input-audit/v1',
        'status':'PASS' if result['candidates'] else 'BLOCKED','target':access.get('target'),'sources':sources,
        'request_binding':request.get('sources'),'failures':result['failures'],'materializable':False})
    write(out/'symmetry-map.json',{'axis':request.get('axis'),'groups':request.get('groups',[]),
        'required_nets':[n['net'] for n in request.get('nets',[])],'request_sha256':sources['request_sha256']})
    try:levels=derive_levels(profile,request.get('metal_levels'))
    except ValueError:levels={}
    write(out/'drc-rule-table.json',{'schema':'analog-layout-symmetric-route.rule-table/v1','profile_fingerprint':sources['profile_fingerprint'],
        'metal_levels':levels,'layer_rules':profile.get('routing_layers',[]),'cut_rules':request.get('cut_rules',{}),
        'cross_cut_rules':request.get('cross_cut_rules',[]),'via_mirror_evidence':request.get('via_mirror_evidence',{}),
        'not_checked':['native polygon and unrepresented conditional rules','live geometry/readback','foundry DRC/LVS','IR/EM','PEX'],
        'rule_source_review':'Supplied hash-bound evidence; site qualification and foundry checks remain separate',
        'materializable':False})
    rows=['# Offline joint symmetric routing review','',
          'Status: '+result['status']+'. Accepted candidates: '+str(len(result['candidates']))+'.',
          'Backend: '+result['backend']+'. No OA write or foundry/signoff run.',
          '','Inputs, complete group mapping and sourced selected rules are bound in input-audit.json, symmetry-map.json and drc-rule-table.json.',
          'Candidate audits reconstruct both sides, verify physical access/connectivity, metal/cuts/landings, directions and mirror unions.',
          'Bends include adjacent-layer direction changes. Length metrics use compacted collinear unions.',
          '','Search statistics: '+json.dumps(result['search_statistics'],sort_keys=True)+'.',
          'Bounded search is not a proof of global feasibility/infeasibility or optimality.',
          '','Live polygon/conditional rules, continuous bus/dual-trunk topology, capacity, DRC/LVS and parasitic/environment checks remain application gates.']
    if result['failures']:
        rows+=['','Failures/attempt diagnostics:']
        rows+=['- '+f['code']+': '+str(f['reason']) for f in result['failures']]
    (out/'routing-review.md').write_text('\n'.join(rows)+'\n',encoding='utf-8')

def selected(out,candidate,intent,request):
    out=Path(out);audit=candidate['audit']
    write(out/'symmetry-audit.json',{'status':audit['status'],'axis':request['axis'],
        'groups':audit['symmetry']['groups'],'cut_array_reflection_checked':True,
        'sources':audit['sources'],'materializable':False})
    write(out/'drc-preflight.json',{'status':'SELECTED_RULES_PASS' if audit['status']=='PASS' else 'BLOCKED',
        'checked':audit['checked'],'not_checked':audit['not_checked'],'errors':audit['errors'],
        'sources':audit['sources'],'materializable':False,'foundry_drc_run':False})
    write(out/'direction-audit.json',{'status':audit['status'],'preferred_directions':intent['preferred_directions'],
        'nets':{n:m['direction_lengths_um'] for n,m in intent['net_metrics'].items()},
        'hard_constraint':'Odd actual metal levels vertical; even horizontal','sources':audit['sources']})
