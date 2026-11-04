"""Deterministic estimands. Computational checks are not causal certification."""
import sqlite3
import numpy as np
from scipy.stats import t
import pandas as pd
from .common import write_json
from .environment import Environment


def estimate(rows, product_ids, *, site_ids=None, confidence=.975):
    if not 0<confidence<1: raise ValueError('confidence must be between zero and one')
    selected=rows[rows.sku.isin(product_ids)]
    if site_ids: selected=selected[selected.site.isin(site_ids)]
    if selected.empty or set(product_ids)-set(selected.sku): raise ValueError('received outcome products required')
    daily=selected.groupby(['site','day','treatment']).sales.sum().reset_index()
    means=daily.groupby(['site','treatment']).sales.mean().unstack()
    if set(means.columns)!={0,1} or means.isna().any().any(): raise ValueError('both arms required in every included site')
    effects=means[1]-means[0]; n=len(effects)
    if n<2: raise ValueError('at least two site clusters required')
    mean=float(effects.mean()); se=float(effects.std(ddof=1)/np.sqrt(n)); critical=float(t.ppf((1+confidence)/2,n-1))
    return {'product_ids':list(product_ids),'site_ids':list(means.index),'aggregation':'sum selected SKU/hour recorded sales within site-day',
        'estimator':'mean of within-site treated-control differences','unit':'items/site-business-day',
        'observation_unit':'site-day','allocation_unit':'site-day','cluster_unit':'site','clusters':n,'df':n-1,
        'site_day_units':len(daily),'estimate':mean,'se':se,'confidence':confidence,'alpha':1-confidence,
        'critical_quantile':(1+confidence)/2,'critical_value':critical,'interval':[mean-critical*se,mean+critical*se],
        'scientific_certification':False}


def prediction_verdict(stat, prediction):
    lo,hi=stat['interval']; threshold=prediction['minimum_effect']
    if prediction['direction']=='decrease': lo,hi=-hi,-lo
    return 'supported' if lo>threshold else 'refuted' if hi<threshold else 'unresolved'


class CheckedEnvironment(Environment):
    def materialize(self,public):
        protocols=super().materialize(public)
        with sqlite3.connect(public/'business.sqlite') as con:
            units=con.execute('SELECT count(*),count(distinct day),count(distinct site),count(distinct sku),count(distinct hour) FROM hourly').fetchone()
        write_json(public/'observed_facts.json',dict(zip(('row_count','business_days','sites','skus','hours'),units)) |
            {'calendar_window_days':84,'interpretation':'Observed history dimensions, not hidden mechanisms or independent sample sizes.'})
        return protocols

    def execute(self, public, directory, plan, slot):
        receipt=super().execute(public,directory,plan,slot)
        if plan['protocol']['is_new_sample']:
            rows=pd.read_csv(directory/'observations.csv'); prediction=plan.get('effect_prediction')
            primary=estimate(rows,plan['outcome_product_ids'],site_ids=(prediction or {}).get('site_ids'))
            secondary={name:estimate(rows,ids) for name,ids in plan.get('outcome_groups',{}).items()}
            statistics={'primary':primary,'secondary':secondary,
                'calendar':{'calendar_days_requested':plan['protocol']['calendar_days'],'business_days_observed':int(rows.day.nunique()),
                            'business_dates':sorted(rows.date.unique().tolist()),'first_calendar_day':84+slot*14,'last_calendar_day_inclusive':84+slot*14+13},
                'interpretation':'Statistical compatibility of this estimand only; no unique mechanism or latent-demand certification.'}
            if prediction: statistics['prediction_check']={'registered_prediction':prediction,'compatible_verdict':prediction_verdict(primary,prediction)}
            receipt['statistics']=statistics
            receipt['summary'].update(mean_daily_sales_difference=primary['estimate'],cluster_interval_97_5=primary['interval'],
                selected_outcome_product_ids=primary['product_ids'],outcome_aggregation=primary['aggregation'],
                confidence=primary['confidence'],critical_quantile=primary['critical_quantile'],df=primary['df'],
                site_clusters=primary['clusters'],site_day_units=primary['site_day_units'],calendar=statistics['calendar'])
            write_json(directory/'backend_receipt.json',receipt)
        return receipt
