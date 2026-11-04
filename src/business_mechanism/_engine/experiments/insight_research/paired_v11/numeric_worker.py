"""Sandbox worker. CONFIG is supplied by the typed lawful-file adapter."""
import hashlib,json,math,os,sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import t

def interval(values,confidence):
    xs=np.asarray(values,dtype=float);n=len(xs);m=float(xs.mean())
    if n<2:return {'estimate':m,'clusters':n,'df':n-1,'confidence':confidence,'se':None,'interval':None,'uncertainty':'insufficient clusters for this t interval'}
    se=float(xs.std(ddof=1)/math.sqrt(n));q=float(t.ppf((1+confidence)/2,n-1))
    return {'estimate':m,'se':se,'clusters':n,'df':n-1,'confidence':confidence,'interval':[m-q*se,m+q*se]}

def compute(c):
    path=Path(c['source_path']);suffix=path.suffix.lower()
    if suffix=='.csv':df=pd.read_csv(path)
    elif suffix in ('.sqlite','.db'):
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:df=pd.read_sql_query('SELECT * FROM hourly',db)
    else:raise ValueError('received observations CSV or hourly SQLite database required')
    need={'site','day','sku','hour','sales'}
    if not need<=set(df):raise ValueError('missing required columns: '+str(sorted(need-set(df))))
    if df.duplicated(['site','day','sku','hour']).any():raise ValueError('duplicate site/day/sku/hour rows; reconcile before aggregation')
    if c['first_day'] is not None and c['last_day'] is not None and c['first_day']>c['last_day']:raise ValueError('first_day exceeds last_day')
    products=list(dict.fromkeys(c['product_ids']+c['comparison_product_ids']))
    if set(products)-set(df.sku):raise ValueError('requested product IDs absent from received data')
    if c['site_ids'] and set(c['site_ids'])-set(df.site):raise ValueError('requested site IDs absent from received data')
    df=df[df.sku.isin(products)]
    if c['site_ids']:df=df[df.site.isin(c['site_ids'])]
    if c['first_day'] is not None:df=df[df.day>=c['first_day']]
    if c['last_day'] is not None:df=df[df.day<=c['last_day']]
    if df.empty:raise ValueError('empty selected data; no zero-valued estimate substituted')
    if not np.isfinite(df[['day','hour','sales']].to_numpy(dtype=float)).all():raise ValueError('nonfinite selected measurements')
    scope={'source_ref':c['source_ref'],'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
      'analysis':c['analysis'],'product_ids':c['product_ids'],'comparison_product_ids':c['comparison_product_ids'],
      'site_ids':sorted(df.site.unique().tolist()),'requested_days':[c['first_day'],c['last_day']],
      'observed_day_range':[int(df.day.min()),int(df.day.max())],'business_days_observed':int(df.day.nunique()),
      'hours_observed':sorted(int(x) for x in df.hour.unique()),'selected_sku_hour_rows':len(df),
      'scope_warning':'Ranges/units describe received records, not latent demand, independent counts or causal identification.'}
    result={'scope':scope,'is_new_sample':False,'scientific_certification':False}
    if c['analysis']=='daily_sales_effect':
        if 'treatment' not in df or set(df.treatment.unique())!={0,1}:raise ValueError('both received treatment0/1 arms required')
        if df.groupby(['site','day']).treatment.nunique().max()!=1:raise ValueError('assignment inconsistent within site-day')
        def effects(skus,sites):
            sub=df[df.site.isin(sites)&df.sku.isin(skus)]
            daily=sub.groupby(['site','day','treatment']).sales.sum().reset_index()
            means=daily.groupby(['site','treatment']).sales.mean().unstack()
            if set(means.columns)!={0,1} or means.isna().any().any():raise ValueError('each selected site needs both arms; no silent site dropping')
            return means[1]-means[0],len(daily)
        groups={'all_selected_sites':scope['site_ids'],**c['site_groups']};estimates={}
        for name,sites in groups.items():
            if not sites or len(sites)!=len(set(sites)) or set(sites)-set(scope['site_ids']):raise ValueError('site_groups must be distinct nonempty subsets of selected sites')
            delta,units=effects(c['product_ids'],sites)
            if c['comparison_product_ids']:
                other,other_units=effects(c['comparison_product_ids'],sites)
                if units!=other_units or not delta.index.equals(other.index):raise ValueError('contrast scopes differ')
                delta=delta-other
            estimates[name]={**interval(delta.values,c['confidence']),'site_ids':list(delta.index),'product_ids':c['product_ids'],
                'comparison_product_ids':c['comparison_product_ids'],'site_day_units':units,
                'site_effects':{str(k):float(v) for k,v in delta.items()},'contrast':'treatment1 minus control0; optional paired difference of product-group effects',
                'unit':'recorded items per site-business-day','interpretation':'Interval containing0 does not establish no effect/equivalence. Same seen sample; subgroup may be posthoc.'}
        result['estimates']=estimates
    elif c['analysis']=='inventory_by_arm':
        if 'opening_stock' not in df:raise ValueError('received opening_stock required')
        first=df[df.hour==df.groupby(['site','day','sku']).hour.transform('min')]
        # First observed hour is explicit; never hard-code9/10 or imply a true
        # physical opening if the received file itself starts later.
        if 'treatment' not in df:df=df.assign(treatment='observed');first=first.assign(treatment='observed')
        if not set(df.treatment.unique())<={0,1,'observed'}:raise ValueError('unknown treatment labels')
        result['groups']={}
        for (arm,sku),g in df.groupby(['treatment','sku']):
            start=first[(first.treatment==arm)&(first.sku==sku)]
            result['groups'][str(arm)+':'+sku]={'arm':str(arm),'product_id':sku,'site_day_units':len(start),
                'selection':'earliest OBSERVED hour within each received site-day-SKU',
                'first_observed_hours':sorted(int(x) for x in start.hour.unique()),
                'first_observed_stock_counts':{str(float(k)):int(v) for k,v in start.opening_stock.value_counts().items()},
                'zero_opening_inventory_sku_hour_rows':int((g.opening_stock==0).sum()),
                'zero_available_minutes_sku_hour_rows':int((g.available_minutes==0).sum()) if 'available_minutes' in g else None,
                'unit':'site-day-SKU counts and SKU-hour row counts; no pooling arms'}
    else:
        if not {'opening_stock','closing_stock','restock'}<=set(df):raise ValueError('inventory ledger columns required')
        gap=df.opening_stock+df.restock-df.closing_stock-df.sales
        result['record_balance']={'rows':len(df),'mismatched_rows':int((gap!=0).sum()),'difference_units':float(gap.sum()),
          'by_product':{str(k):{'rows':len(g),'mismatched_rows':int((gap.loc[g.index]!=0).sum()),'difference_units':float(gap.loc[g.index].sum())} for k,g in df.groupby('sku')},
          'interpretation':'Internal ledger equality only; not an independent physical count or proof of the error cause.'}
    return result

if __name__=='__main__':
    output=compute(CONFIG)
    destination=Path(os.environ['WORK_DIR'])/'evidence_statistic.json'
    destination.write_text(json.dumps(output,ensure_ascii=False,allow_nan=False)+'\n')
    print('Scoped reanalysis saved; not a new sample or scientific certification.')
