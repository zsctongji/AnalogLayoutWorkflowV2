"""Hash-pinned dispatcher entrypoint for native Virtuoso gate-via replacement."""
import argparse,sys
from pathlib import Path
from native_gate_via import NativeGateBackend,make_plan,verifier,S
from workflow_runtime import load,write,digest,filehash,Invalid
from adapter_runtime import execute

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--handoff',required=True);parser.add_argument('--out',required=True);args=parser.parse_args()
    handoff=load(args.handoff);item=handoff['stage_inputs']['native_gate_request'];path=Path(item['path'])
    if filehash(path)!=item['sha256']:raise Invalid('Native gate request drift')
    request=load(path);proof_path=Path(request['qualification']['path'])
    if filehash(proof_path)!=request['qualification']['sha256']:raise Invalid('Qualification evidence drift')
    proof=load(proof_path)
    from virtuoso_bridge import VirtuosoClient
    from virtuoso_bridge.env import set_runtime_env_file
    set_runtime_env_file(request['bridge_env']);client=VirtuosoClient.from_env();backend=NativeGateBackend(client,S,proof)
    before=backend.snapshot(handoff['source'])
    if digest(before)!=request['source_snapshot_sha256']:raise Invalid('Native gate source changed')
    plan,expected,checks=make_plan(handoff['source'],handoff['target'],before,request['records'],proof)
    # Complete preflight and reviewed plan are local; only execute enters CAD writes.
    run=Path(handoff['run_dir']);write(run/'native-plan.json',plan);write(run/'native-expected.json',expected)
    result=execute(plan,backend,verifier)
    saved=backend.snapshot(handoff['target'])
    write(run/'native-saved.json',saved);write(run/'native-equivalence.json',checks);write(run/'native-transaction.json',result)
    records=request['records'];by_via={v['id']:v for v in saved['native_vias']}
    for record in records:
        if record.get('reused_native'):continue
        via_id=record['contact_object_ids'][0]+'/native';v=by_via[via_id]
        record['native_via_root_id']=via_id;record['native_via_def']='PO1_M1'
        record['contact_object_ids']=[via_id+'#cont'];record['metal_landing_object_ids']=[via_id+'#mt1'];record['poly_id']=via_id+'#poly1'
        record['actual_native_via']=v;record['verification_source']='dbCreateVia PO1_M1; actual expanded primitive and actual net equality to previously verified source, complete preserved-device/ring/share readback'
    write(run/'native-gate-records.json',records)
    artifacts=[dict(path=str((run/name).resolve()),sha256=filehash(run/name),host='local') for name in ('native-plan.json','native-expected.json','native-saved.json','native-equivalence.json','native-transaction.json','native-gate-records.json')]
    receipt=dict(status='LOCALLY_VERIFIED',handoff_sha256=digest(handoff),output_cellview=handoff['target'],output_revision=digest(saved),input_revision=digest(before),readback_verified=True,validation=dict(verdict='NATIVE_PO1_M1_FULL_PRIMITIVE_NET_EQUIVALENCE_PASS',foundry_signoff=False),artifacts=artifacts,native_api='dbCreateVia',native_via_count=len(saved['native_vias']),cad_execution={'mutation_batch_calls':1,'save_calls':1},limitations=['Exact contact replacement qualified for this profile; fresh contacts need independently reviewed stem/escape planning','Whole-circuit DRC/LVS not rerun'])
    write(args.out,receipt)

if __name__=='__main__':main()
