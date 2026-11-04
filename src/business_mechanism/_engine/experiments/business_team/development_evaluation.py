"""Executable public evaluation contract and observed development receipts.

No latent demand, world kind or final observations are exposed here. Repeated
evaluation of an identical program/condition reuses its original receipt.
"""
import hashlib
import json
from pathlib import Path
import pandas as pd
from contracts import field_definition


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def initialize(ws):
    from workspace import write_json
    from decision_interface import load as load_decision_interface
    interface = load_decision_interface(ws)
    contract={
        'version':'development-evaluation-v2-observable-logs','scenario_version':ws.world.scenario_version,
        'conditions':{
            'standard':{'simulation_seed':ws.world.seed,'first_day':112,'calendar_days':14},
            'replication_1':{'simulation_seed':ws.world.seed+104729,'first_day':112,'calendar_days':14}},
        'fixed':{'training':'received history.csv, exact SHA recorded with each receipt',
                 'economics':'received product prices, unit costs, salvage and fixed newsvendor rule',
                 'supply':'same public operating policy in each condition; no algorithm control of support goods'},
        'supported_controls':['registered condition_id','provided or registered program_id'],
        'unsupported_controls':['arbitrary seed','cost-ratio or price changes','latent demand inspection','final holdout access'],
        'observed_metrics':{'net_profit':'yuan/site-day','fresh_waste':'fresh leftover items/site-day',
                            'observed_stockout_hours':'number of fresh SKU-hour records with available_minutes<60; not a duration in clock hours'},
        'random_streams':'simulation_seed changes traffic, support supply and demand random streams under the same rules; paired programs share streams within a condition',
        'observation_unit':['site','day'],'dependence':'Repeated days within a site; common exogenous random streams within each condition. Additional streams are sensitivity checks, not new independent sites/worlds.',
        'observation_exports':{
            'forecast_rows':{'key':['site','day','sku','hour'],'scope':'Exact morning prediction inputs plus predicted_demand_mean. Input fields are available at 09:00; output is the program demand-mean estimate, not observed demand.'},
            'observed_hourly':{'key':['site','day','sku','hour'],'scope':'Only columns declared in public data_dictionary.tables.hourly. Stocks/recorded sales/availability are observed at their declared times; outcomes cannot become morning predictors.'},
            'daily_finance':{'key':['site','day'],'scope':'Only public daily finance fields, after day close; no invented hourly profit allocation.'},
            'site_days':{'key':['site','day'],'scope':'Daily finance and affected fresh SKU-hour record counts, reconstructible from the observable logs.'}},
        'interpretation':'Conditional operational observations, not demand accuracy, unique mechanism proof or generalisation. Paired uncertainty requires matching condition and site/day; inference assumptions belong in the analysis.',
    }
    if interface:
        from workspace import sha
        contract['version'] = 'development-evaluation-v3-observed-decisions'
        contract['decision_interface'] = {'file': 'decision_interface.json',
            'sha256': sha(ws.public / 'decision_interface.json'),
            'ordering_policy_sha256': interface['implementation']['sha256']}
        definition = interface['exports']['order_decisions']
        contract['observation_exports']['order_decisions'] = {
            'key': definition['key'], 'scope': definition['scope'],
            'schema_source': 'decision_interface.json#exports.order_decisions',
            'storage': definition['storage']}
    path=ws.public/'evaluation_contract.json'
    if path.exists() and json.loads(path.read_text())!=contract:
        raise ValueError('evaluation contract changed; use a new scenario/phase, not an in-place continuation')
    write_json(path,contract)
    ws.registered_sources.add(str(path))
    ws.state.setdefault('development_evaluations',[])
    ws.state.setdefault('evaluation_reviews',[])


def program(ws,program_id):
    from workspace import sha
    if program_id in ('baseline','numeric_refit','strong_numeric'):
        return ws.public/(program_id+'.py')
    item=next((a for a in ws.state['algorithms'] if a['id']==program_id),None)
    if item:
        path=ws.readable(item['code_file'])
        if sha(path)!=item['code_sha256']:raise ValueError('registered program bytes changed; register a new version')
        return path
    raise ValueError('select a provided or actually registered program_id')


def describe(ws):
    from workspace import sha
    contract=json.loads((ws.public/'evaluation_contract.json').read_text())
    ids=['baseline','numeric_refit','strong_numeric']+[a['id'] for a in ws.state['algorithms']]
    return {'contract':contract,'contract_sha256':sha(ws.public/'evaluation_contract.json'),
            'programs':[{'program_id':pid,'code_file':str(program(ws,pid)),'code_sha256':sha(program(ws,pid)),
                         'selectable':True} for pid in ids],
            'evaluations':[{k:v for k,v in e.items() if k!='execution_receipt'} for e in ws.state.get('development_evaluations',[])],
            'evaluation_reviews':ws.state.get('evaluation_reviews',[])}


def register_sources(ws,receipt):
    paths=[str(ws.readable(receipt['observations'])),str(ws.readable(receipt['receipt_file']))]
    for item in receipt.get('observation_files',{}).values():
        paths.extend([str(ws.readable(item['path'])),str(ws.readable(item['metadata_file']))])
    ws.registered_sources.update(paths);ws.registered_data_sources.update(paths)


def observation_frames(ws,features,forecasts,rows,finances,observations,decision_trace=None):
    """Project public observables; never infer latent demand or special verdicts."""
    dictionary=json.loads((ws.public/'data_dictionary.json').read_text())
    hourly_columns=list(dictionary['tables']['hourly']['columns'])
    daily_columns=list(dictionary['tables']['daily_finance']['columns'])
    forecast_columns=list(dictionary['tables']['prediction_features']['columns']) if 'prediction_features' in dictionary['tables'] else list(features)
    if set(features)!=set(forecast_columns):raise ValueError('prediction feature columns differ from public input contract')
    forecast_frame=features.copy()
    forecast_frame['predicted_demand_mean']=forecasts
    frames={'forecast_rows':forecast_frame,'observed_hourly':rows[hourly_columns].copy(),
            'daily_finance':finances[daily_columns].copy(),'site_days':observations.copy()}
    keys={'forecast_rows':['site','day','sku','hour'],'observed_hourly':['site','day','sku','hour'],
          'daily_finance':['site','day'],'site_days':['site','day']}
    if decision_trace is not None:
        from decision_interface import exported_definition
        definition = exported_definition(ws, 'order_decisions')
        if definition is None:
            raise ValueError('decision trace needs a registered public schema')
        frames['order_decisions'] = decision_trace[list(definition['columns'])].copy()
        keys['order_decisions'] = definition['key']
    for name,frame in frames.items():
        if frame.duplicated(keys[name]).any() or frame[keys[name]].isna().any().any():
            raise ValueError('non-unique or missing observation keys: '+name)
    key=keys['forecast_rows']
    observed=frames['observed_hourly'];covered=observed[observed.sku.isin(features.sku.unique())]
    if set(map(tuple,features[key].to_numpy()))!=set(map(tuple,covered[key].to_numpy())):
        raise ValueError('forecast and observed sale-goods keys do not align')
    return frames,keys


def evaluate(ws,filename,condition_id='standard',name='development'):
    from workspace import sha,write_json
    from world import OfficeWorld,operating_orders,START
    from decision_interface import load as load_decision_interface
    interface = load_decision_interface(ws)
    contract_path=ws.public/'evaluation_contract.json'
    contract=json.loads(contract_path.read_text())
    if interface and contract.get('decision_interface') != {
            'file': 'decision_interface.json',
            'sha256': sha(ws.public/'decision_interface.json'),
            'ordering_policy_sha256': interface['implementation']['sha256']}:
        raise ValueError('decision interface changed relative to the evaluation contract; use a new phase')
    if condition_id not in contract['conditions']:raise ValueError('use a registered evaluation condition_id: '+str(list(contract['conditions'])))
    condition=contract['conditions'][condition_id]
    code=ws.readable(filename)
    identity={'code_sha256':sha(code),'history_sha256':sha(ws.public/'history.csv'),
              'contract_sha256':sha(contract_path),'condition_id':condition_id,'condition':condition}
    if interface:
        identity.update(decision_policy_sha256=interface['implementation']['sha256'],
                        decision_interface_sha256=sha(ws.public/'decision_interface.json'))
    key=digest(identity)
    previous=next((e for e in ws.state['development_evaluations'] if e['identity_sha256']==key),None)
    if previous:
        checks=[(previous['observations'],previous['observations_sha256'])]
        for item in previous.get('observation_files',{}).values():
            checks.extend([(item['path'],item['sha256']),(item['metadata_file'],item['metadata_sha256'])])
        for file,expected in checks:
            if sha(ws.readable(file))!=expected:raise ValueError('development observations changed; do not silently regenerate')
        register_sources(ws,previous)
        return {**previous,'reused_existing_receipt':True}
    world=OfficeWorld(ws.world.kind,condition['simulation_seed'],ws.world.scenario_version)
    features=world.features(condition['first_day'],condition['calendar_days'])
    forecasts,execution=ws.workers['evaluator'].forecast(code,ws.public/'history.csv',features,name)
    if interface:
        orders, decision_trace = operating_orders(features, forecasts, with_trace=True)
    else:
        orders, decision_trace = operating_orders(features, forecasts), None
    rows,finances=world.generate(condition['first_day'],condition['calendar_days'],orders=orders)
    if decision_trace is not None:
        from ordering_policy import attach_execution
        decision_trace = attach_execution(decision_trace, rows)
    fresh_ids=set(pd.read_csv(ws.public/'products.csv').query("category == '鲜食'").sku)
    counts=rows[rows.sku.isin(fresh_ids)].assign(observed_stockout_hours=lambda d:(d.available_minutes<60).astype(int)).groupby(['site','day']).observed_stockout_hours.sum()
    observations=finances[['site','day','date','net_profit','fresh_waste']].merge(counts,on=['site','day'],validate='one_to_one')
    if observations.duplicated(['site','day']).any():raise ValueError('non-unique operating observation unit')
    eid=f"D{len(ws.state['development_evaluations'])+1:04d}"
    folder=ws.shared/'development_evaluations'/eid;folder.mkdir(parents=True)
    frames,keys=observation_frames(ws,features,forecasts,rows,finances,observations,decision_trace)
    files={}
    for table,frame in frames.items():
        definitions = (interface['exports']['order_decisions']['columns'] if table == 'order_decisions'
                       else {c:field_definition(c,structured=True) for c in frame})
        target=folder/(table+'.csv');frame.to_csv(target,index=False)
        metadata=ws.annotate(target,{'producer':'environment','row_grain':'one row per '+' × '.join(keys[table]),'key':keys[table],'columns':list(frame),
            'column_definitions':definitions,
            'condition':condition,'code_sha256':identity['code_sha256'],'training_history_sha256':identity['history_sha256'],
            'evaluation_contract_sha256':identity['contract_sha256'],
            **({'decision_policy_sha256': identity['decision_policy_sha256'],
                'decision_interface_sha256': identity['decision_interface_sha256']} if interface else {}),
            'input_columns':list(features) if table=='forecast_rows' else [],
            'semantics_status':contract['observation_exports'][table]['scope']})
        files[table]={'path':str(target),'sha256':sha(target),'row_count':len(frame),'key':keys[table],
                      'metadata_file':metadata,'metadata_sha256':sha(metadata)}
    target=Path(files['site_days']['path'])
    receipt={'evaluation_id':eid,**identity,'identity_sha256':key,'code_file':str(code),
             'mean_net_profit_per_site_day':float(observations.net_profit.mean()),
             'mean_fresh_waste_per_site_day':float(observations.fresh_waste.mean()),
             'observed_stockout_hours':int(observations.observed_stockout_hours.sum()),'site_days':len(observations),
             'evaluation_dates':[str((START+pd.Timedelta(days=condition['first_day'])).date()),str((START+pd.Timedelta(days=condition['first_day']+condition['calendar_days']-1)).date())],
             'observations':str(target),'observations_sha256':sha(target),'receipt_file':str(folder/'receipt.json'),
             'observation_files':files,
             'execution_receipt':execution,'note':contract['interpretation'],'reused_existing_receipt':False}
    write_json(folder/'receipt.json',receipt)
    ws.state['development_evaluations'].append(receipt);register_sources(ws,receipt);ws.persist()
    return receipt
