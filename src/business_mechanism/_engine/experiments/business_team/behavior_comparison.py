"""Compare observed program behavior at each causal link, without grading claims."""
import numpy as np
import pandas as pd
from workspace import sha


def compare(left,right):
    fields=('history_sha256','contract_sha256','condition_id','condition','decision_policy_sha256','decision_interface_sha256')
    if any(left.get(k)!=right.get(k) for k in fields):raise ValueError('behavior comparison needs matched inputs, condition and decision policy')
    reports={}
    for table,column in (('forecast_rows','predicted_demand_mean'),('order_decisions','order_quantity'),('site_days','net_profit')):
        a=left.get('observation_files',{}).get(table);b=right.get('observation_files',{}).get(table)
        if not a or not b:
            reports[table]={'status':'unavailable'};continue
        if a['key']!=b['key']:raise ValueError('comparison keys differ')
        for source in (a,b):
            if sha(source['path'])!=source['sha256']:raise ValueError('comparison input bytes changed')
        key=a['key'];x=pd.read_csv(a['path']);y=pd.read_csv(b['path'])
        pair=x[key+[column]].merge(y[key+[column]],on=key,how='outer',validate='one_to_one',indicator=True,suffixes=('_left','_right'))
        if not pair['_merge'].eq('both').all():raise ValueError('comparison populations differ')
        delta=pair[column+'_left']-pair[column+'_right']
        if not np.isfinite(delta).all():raise ValueError('nonfinite comparison values')
        changed=np.abs(delta)>1e-9
        report={'status':'compared','rows':len(pair),'changed_rows':int(changed.sum()),
                'absolute_delta_sum':float(np.abs(delta).sum()),'signed_delta_sum':float(delta.sum()),
                'absolute_tolerance':1e-9,'left_sha256':a['sha256'],'right_sha256':b['sha256']}
        if 'sku' in key:report['changed_rows_by_sku']=pair.assign(changed=changed).groupby('sku').changed.sum().astype(int).to_dict()
        reports[table]=report
    return {'left_evaluation_id':left.get('evaluation_id'),'right_evaluation_id':right.get('evaluation_id'),
            'comparisons':reports,'interpretation':'Observed prediction -> order -> profit differences under one matched condition. Zero change is a valid result. Numerical changes do not prove a mechanism, statistical effect, generalisation or improvement.'}
