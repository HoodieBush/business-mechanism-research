"""Bind a proposed intervention to an executable capability before sampling.

Checks describe what the operation actually changes, never whether a hypothesis
or measured scientific result is correct. No private demand/world labels here.
"""
import hashlib
import json
from scenario_contract import SALE_STOCK_CAP,SUPPORT_STOCK_CAP

FRESH_TRIAL_OPENING = SALE_STOCK_CAP
SUPPORT_TRIAL_OPENING = SUPPORT_STOCK_CAP
TRIAL_CALENDAR_DAYS = 14
TRIAL_ALPHA = .025


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def match_changed_variables(expected,protocol):
    actual=protocol['changed_variables']
    if len(expected)!=len(set(expected)) or set(expected)!=set(actual):
        raise ValueError('requested intervention does not match executable protocol; '
            +json.dumps({'requested':expected,'actual':actual,'fixed_variables':protocol['fixed_variables']},ensure_ascii=False))


def capabilities(products):
    fresh=products.loc[products.category=='鲜食','sku'].tolist()
    result={'inventory_records':{
        'id':'inventory_records','kind':'inventory_audit','support_sku':None,
        'changed_variables':[],'fixed_variables':{},'is_new_sample':False,
        'measurement':'reconcile received opening + restock - closing with recorded sales; no new physical count or demand observation'}}
    for sku in products.loc[products.category=='配套用品','sku']:
        key='support_supply:'+sku
        result[key]={'id':key,'kind':'supply_trial','support_sku':sku,
            'changed_variables':['morning_stock:'+sku],
            'arms':{'control':{'morning_stock:'+sku:'usual operational supply'},
                    'treatment':{'morning_stock:'+sku:SUPPORT_TRIAL_OPENING}},
            'fixed_variables':{**{'morning_stock:'+p:FRESH_TRIAL_OPENING for p in fresh},
                'prices':'unchanged','site_conditions':'unchanged','intraday_replenishment':'none'},
            'assignment_unit':['site','day'],'observation_grain':['site','day','sku','hour'],
            'primary_outcome':{'name':'selected product recorded daily sales','unit':'items/site-day','aggregation':'sum selected SKU/hour sales within site-day'},
            'calendar_days':TRIAL_CALENDAR_DAYS,'alpha':TRIAL_ALPHA,'is_new_sample':True,
            'limits':'Effects concern the specified support-supply intervention with fresh stock held fixed in both arms; not an intervention on fresh stock, not latent demand or unique mechanism proof.'}
    return result


def prepare(workspace,args):
    catalogue=workspace.experiment_capabilities
    if args['protocol_id'] not in catalogue:raise ValueError('choose a received protocol_id: '+str(list(catalogue)))
    protocol=catalogue[args['protocol_id']]
    match_changed_variables(args['expected_changed_variables'],protocol)
    if not any(h['id']==args['hypothesis_id'] for h in workspace.state['hypotheses']):raise ValueError('received hypothesis ID required')
    outcomes=args['outcome_product_ids']
    if len(outcomes)!=len(set(outcomes)) or not set(outcomes).issubset(workspace.history.sku.unique()):raise ValueError('select received outcome SKU IDs; these select measurements, not interventions')
    operation=workspace.operation['id'] if workspace.operation else None
    prior=next((p for p in workspace.state.get('study_plans',[]) if operation and p.get('operation_id')==operation),None)
    if prior:return prior
    item={'id':f"plan_{len(workspace.state.get('study_plans',[]))+1:04d}",
        'hypothesis_id':args['hypothesis_id'],'protocol':protocol,'outcome_product_ids':outcomes,
        'prediction':args['prediction'],'analysis_plan':args['analysis_plan'],
        'operation_id':operation,'state_at_preparation':'prepared_not_executed','note':'No observations produced and no physical trial/alpha consumed by preparation.'}
    item['sha256']=digest(item)
    path=workspace.shared/'study_plans'/(item['id']+'.json');path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(item,ensure_ascii=False,indent=2)+'\n')
    workspace.state.setdefault('study_plans',[]).append(item);workspace.persist();return item


def resolve(workspace,plan_id):
    item=next((p for p in workspace.state.get('study_plans',[]) if p['id']==plan_id),None)
    if not item:raise ValueError('received plan_id required; prepare_experiment first')
    frozen=json.loads(workspace.readable(workspace.shared/'study_plans'/(plan_id+'.json')).read_text())
    body={k:v for k,v in item.items() if k!='sha256'}
    if frozen!=item or digest(body)!=item['sha256']:raise ValueError('prepared plan version changed; prepare a new plan')
    if workspace.experiment_capabilities.get(item['protocol']['id'])!=item['protocol']:raise ValueError('protocol version changed; prepare a new plan')
    protocol=item['protocol']
    args={'hypothesis_id':item['hypothesis_id'],'kind':protocol['kind'],
        'product_ids':item['outcome_product_ids'],'prediction':item['prediction'],
        'controls':json.dumps({'arms':protocol.get('arms'),'fixed_variables':protocol['fixed_variables']},ensure_ascii=False),
        'analysis_plan':item['analysis_plan']}
    if protocol['is_new_sample']:args.update(support_sku=protocol['support_sku'],days=protocol['calendar_days'])
    return item,args
