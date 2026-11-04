"""Developer-only environment checks; no model calls or latent truth in Actor data."""
import argparse
import json
from pathlib import Path
import numpy as np

from execution import PythonWorkspace
from workspace import write_json


def sandbox_probe(directory):
    root=Path(directory)
    public=root/'public';shared=root/'artifacts'
    public.mkdir(parents=True,exist_ok=True);shared.mkdir(parents=True,exist_ok=True)
    # Fixed developer code, not an Agent candidate. No unsandboxed fallback.
    receipt=PythonWorkspace(shared/'probe',public,shared,per_execution=True).run('print("sandbox-ready")')
    return {'ready':receipt['ok'] and receipt.get('stdout','').strip()=='sandbox-ready','receipt':receipt,
            'scope':'Sandbox launch capability in this execution session; isolation is checked separately by test_business_team.'}


def action_space_probe():
    """Does a public legal forecast change actual orders at all? No win target."""
    from world import OfficeWorld,operating_orders
    world=OfficeWorld('confounding',9137,'office-business-v0.3')
    features=world.features(112,14)
    low=np.full(len(features),.1);high=np.full(len(features),10.)
    a,ta=operating_orders(features,low,with_trace=True)
    b,tb=operating_orders(features,high,with_trace=True)
    key=['day','site','sku']
    paired=ta[key+['order_quantity']].merge(tb[key+['order_quantity']],on=key,validate='one_to_one')
    changed=paired.order_quantity_x.ne(paired.order_quantity_y)
    rows,finance=world.generate(112,14,orders=a)
    rows_b,finance_b=world.generate(112,14,orders=b)
    return {'forecast_rows':len(features),'decision_rows':len(paired),'changed_decisions':int(changed.sum()),
            'changed_by_sku':paired.assign(changed=changed).groupby('sku').changed.sum().astype(int).to_dict(),
            'observed_finance_equal':finance.equals(finance_b),
            'site_days':len(finance),'business_window':[112,14],
            'scope':'Two fixed legal control vectors demonstrate action sensitivity, not Agent code execution, improvement, mechanism identification or ample headroom above provided programs.'}


def backend_probe(directory):
    """Actual prepare/resolve/simulation on developer fixtures, without candidate code.

    Constructor is intentionally bypassed: this tests the trial backend, not
    sandbox startup, analysis/review agents or full-workspace readiness.
    """
    from world import OfficeWorld,product_frame,site_frame
    from workspace import ResearchWorkspace
    from experiment_plans import capabilities,prepare,resolve
    root=Path(directory).resolve()
    if root.exists():raise ValueError('backend probe evidence already exists')
    reports={}
    for kind in ('relationship','confounding','record_fault'):
        ws=ResearchWorkspace.__new__(ResearchWorkspace)
        ws.root=root/kind;ws.public=ws.root/'public';ws.shared=ws.root/'artifacts'
        ws.public.mkdir(parents=True);ws.shared.mkdir()
        ws.world=OfficeWorld(kind,9137,'office-business-v0.3')
        ws.history,_=ws.world.generate(0,14)
        product_frame().to_csv(ws.public/'products.csv',index=False);site_frame().to_csv(ws.public/'sites.csv',index=False)
        ws.state={'hypotheses':[{'id':'H_fixture'}],'experiments':[]};ws.operation=None;ws.path_aliases={}
        ws.data_source={'origin':'developer backend fixture, not an Agent execution'}
        ws.experiment_capabilities=capabilities(product_frame())
        outcomes=product_frame().query("category=='鲜食'").sku.tolist()
        chosen=next(p for p in ws.experiment_capabilities.values() if p['is_new_sample'])
        request={'hypothesis_id':'H_fixture','protocol_id':chosen['id'],'outcome_product_ids':outcomes,
                 'expected_changed_variables':chosen['changed_variables'],'prediction':'developer capability fixture; no model discovery',
                 'analysis_plan':'execute the registered arms and preserve scoped observations, including null/noisy results'}
        plan=prepare(ws,request);_,args=resolve(ws,plan['id']);trial=ws.experiment(args)
        inventory=ws.experiment({'hypothesis_id':'H_fixture','kind':'inventory_audit','product_ids':outcomes})
        reports[kind]={'plan_id':plan['id'],'protocol_id':chosen['id'],'trial':trial,'inventory':inventory}
    return {'cases':reports,'real_model_calls':0,'sandbox_used':False,
            'scope':'Developer-controlled prepare -> resolve -> actual backend intervention and record reconciliation. Separate evidence for environment capability; not end-to-end Actor research, a statistical power guarantee or autonomous scientific success.'}


def check(output):
    output=Path(output)
    if output.exists():raise ValueError('readiness evidence already exists; choose a fresh output directory')
    output.mkdir(parents=True)
    result={'sandbox':sandbox_probe(output/'sandbox_probe'),'action_space':action_space_probe(),
            'backend':backend_probe(output/'backend'),
            'real_model_calls':0,'autonomous_scientific_ability_tested':False}
    result['runtime_environment_ready']=False
    result['readiness_status']='full_integration_preflight_required' if result['sandbox']['ready'] else 'sandbox_launch_blocked'
    write_json(output/'readiness.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    print(json.dumps(check(args.output),ensure_ascii=False,indent=2))
