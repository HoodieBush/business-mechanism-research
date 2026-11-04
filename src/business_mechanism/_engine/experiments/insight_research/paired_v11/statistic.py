"""One identical sandbox adapter for researcher and independent critic."""
import json
from pathlib import Path
from ..common import Pending,sha

def inspect(workspace,args,key,run_python):
    path,_=workspace.file(args['source_ref']);version=sha(path)
    config={**args,'source_path':str(path)}
    source=Path(__file__).with_name('numeric_worker.py')
    code='CONFIG = '+repr(config)+'\n'+source.read_text()
    result=run_python({'code':code,'purpose':'Scoped reanalysis of received evidence; no new data or causal certification'},key)
    execution=result.get('execution',{})
    if not execution.get('ok',execution.get('exit_code')==0):return {**result,'ok':False,'error':'Scoped computation failed; original execution retained: '+str(execution.get('stderr',''))[-1600:]}
    artifact=next((f for f in result.get('files',[]) if Path(f['path']).name=='evidence_statistic.json'),None)
    if artifact is None:raise Pending('statistic worker succeeded without durable output; inspect original execution')
    if sha(path)!=version:raise Pending('received source changed during statistic computation')
    computed=json.loads(Path(artifact['path']).read_text())
    if computed['scope']['source_ref']!=args['source_ref'] or computed['scope']['source_sha256']!=version:raise Pending('statistic source binding differs')
    return {'ok':True,'statistics':computed,'statistic_artifact':artifact,'source_ref':args['source_ref'],'source_sha256':version,
       'worker_sha256':sha(source),'execution_receipt':{k:execution.get(k) for k in ('execution_directory','exit_code','ok')},
       'files':result.get('files',[]),'receipt_scope':'Actual sandbox reanalysis, no new sample and no scientific clearance.'}
