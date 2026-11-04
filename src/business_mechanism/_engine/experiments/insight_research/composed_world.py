"""Private v0.5 composition. Never materialize this code or its switches for Actor.

The four existing mechanisms retain their coefficients and random streams.
Demand, supply selection and observation errors are separate interventions.
"""
import numpy as np
import pandas as pd
from .common import ROOT
from world import OfficeWorld, START, product_frame, site_frame, HOURS
from ordering_policy import historical_sale_stock
from experiment_plans import FRESH_TRIAL_OPENING, SUPPORT_TRIAL_OPENING
from scenario_contract import SUPPORT_STOCK_CAP, EXTENDED_VERSION

VERSION = 'office-business-v0.5'
MECHANISMS = ('cutlery_demand', 'supply_selection', 'sales_underrecording', 'site_weekday')


class ComposedWorld(OfficeWorld):
    def __init__(self, kind='composed', seed=9137, scenario_version=VERSION, mechanisms=None):
        if kind != 'composed' or scenario_version != VERSION:
            raise ValueError('explicit composed v0.5 identity required')
        super().__init__('site_weekday', seed, EXTENDED_VERSION)
        selected = MECHANISMS if mechanisms is None else tuple(mechanisms)
        if len(selected) != len(set(selected)) or not set(selected) <= set(MECHANISMS):
            raise ValueError('distinct known private mechanism switches required')
        self.kind, self.scenario_version = kind, scenario_version
        self.mechanisms = tuple(sorted(selected))

    def day_context(self, day, site):
        rng = np.random.default_rng(np.random.SeedSequence([self.seed, day, int(site[1:])-1, 101]))
        low = rng.random() < .35
        traffic = (.58 if low else 1.12) * rng.lognormal(0, .11)
        probability = (.8 if low else .18) if 'supply_selection' in self.mechanisms else .4
        missing = rng.random() < probability
        if 'site_weekday' in self.mechanisms and (START + pd.Timedelta(days=day)).weekday() == 4:
            traffic *= {'C01': .55, 'C05': 1.45}.get(site, 1.)
        return traffic, 0 if missing else SUPPORT_STOCK_CAP

    def generate(self, first_day, days, orders=None, assignment=None, support_sku='S11', main_high=False, corrected=False):
        rows, daily = [], []
        products = product_frame().to_dict('records'); assignment = assignment or {}
        for day in range(first_day, first_day + days):
            date = START + pd.Timedelta(days=day)
            if date.weekday() >= 5: continue
            for site in site_frame().to_dict('records'):
                si = int(site['site'][1:])-1; traffic, _ = self.day_context(day, site['site'])
                inventory = {p['sku']: SUPPORT_STOCK_CAP if p['category']=='配套用品' else historical_sale_stock(p['category']) for p in products}
                inventory.update(self.support_plan(day, site['site']))
                if main_high: inventory.update({p['sku']: FRESH_TRIAL_OPENING for p in products if p['category']=='鲜食'})
                if orders is not None:
                    inventory.update({p['sku']: int(orders[(day,site['site'],p['sku'])]) for p in products[:10]})
                treatment = assignment.get((day,site['site']),0)
                if treatment: inventory[support_sku] = SUPPORT_TRIAL_OPENING
                opening = inventory.copy(); totals = {p['sku']:0 for p in products}
                for hour in HOURS:
                    support_start = {p['sku']:inventory[p['sku']] for p in products[10:]}
                    used_support = {'S11':0,'S12':0}
                    for pi,p in enumerate(products[:10]):
                        rng = np.random.default_rng(np.random.SeedSequence([self.seed,day,si,hour,pi,201]))
                        base = (6.0 if 11<=hour<=13 else .8) if p['category']=='鲜食' else (2.5 if 11<=hour<=14 else 1.4)*(1-.045*pi)
                        rate = base*(.83+.065*si)*traffic*(1+.03*date.weekday())
                        if 'cutlery_demand' in self.mechanisms and p['sku']=='S01' and not site['pantry_cutlery'] and support_start['S11']==0:
                            rate *= np.exp(-1.05)
                        demand = int(rng.poisson(rate)); stock = inventory[p['sku']]; sold = min(stock,demand)
                        inventory[p['sku']] -= sold; totals[p['sku']] += sold
                        available = 60 if inventory[p['sku']]>0 else (int(60*rng.beta(stock,demand-stock+1)) if stock>0 else 0)
                        recorded = sold
                        if 'sales_underrecording' in self.mechanisms and si in (0,1,3,6) and p['sku']=='S01' and not corrected:
                            recorded = int(rng.binomial(sold,.62))
                        if p['sku']=='S01' and not site['pantry_cutlery']:
                            issued = min(inventory['S11'],sold); inventory['S11']-=issued
                            used_support['S11']+=issued; totals['S11']+=issued
                        if p['category']=='鲜食':
                            issued = min(inventory['S12'],sold); inventory['S12']-=issued
                            used_support['S12']+=issued; totals['S12']+=issued
                        rows.append(dict(day=day,date=date.strftime('%Y-%m-%d'),weekday=date.weekday(),hour=hour,site=site['site'],sku=p['sku'],price=p['price'],sales=recorded,opening_stock=stock,closing_stock=inventory[p['sku']],restock=0,available_minutes=available,treatment=treatment))
                    for p in products[10:]:
                        rows.append(dict(day=day,date=date.strftime('%Y-%m-%d'),weekday=date.weekday(),hour=hour,site=site['site'],sku=p['sku'],price=p['price'],sales=used_support[p['sku']],opening_stock=support_start[p['sku']],closing_stock=inventory[p['sku']],restock=0,available_minutes=60 if inventory[p['sku']]>0 else 0,treatment=treatment))
                profit=0.; waste=0
                for p in products:
                    q,sold=opening[p['sku']],totals[p['sku']]
                    profit += -p['unit_cost']*sold if p['category']=='配套用品' else p['price']*sold-p['unit_cost']*q+p['salvage']*(q-sold)
                    if p['category']=='鲜食': waste += q-sold
                daily.append(dict(day=day,date=date.strftime('%Y-%m-%d'),site=site['site'],net_profit=profit,fresh_waste=waste,treatment=treatment))
        return pd.DataFrame(rows),pd.DataFrame(daily)


def create_world(**spec):
    return ComposedWorld(**spec) if spec.get('kind')=='composed' else OfficeWorld(**spec)
