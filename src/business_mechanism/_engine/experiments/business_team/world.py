"""Private synthetic vending business. Never mounted into an Agent workspace."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
from contracts import HOURS, OPENING_HOURS
from experiment_plans import FRESH_TRIAL_OPENING,SUPPORT_TRIAL_OPENING
from scenario_contract import LEGACY_VERSION, VERSION as REVISED_VERSION, SALE_STOCK_CAP, SUPPORT_STOCK_CAP
from scenario_contract import EXTENDED_VERSION
from ordering_policy import historical_sale_stock

VERSION = "office-business-v0.2"
START = pd.Timestamp("2026-01-05")
PRODUCTS = [
    ("S01", "鲜食", "冷藏鸡肉饭，包装不附用餐工具", 18., 9., 0., 1, 0),
    ("S02", "鲜食", "便当套餐，包装自带一次性勺叉", 20., 10., 0., 1, 1),
    ("S03", "饮料", "瓶装饮用水", 3., 1., 1., 30, 0),
    ("S04", "饮料", "无糖茶饮", 6., 2.5, 2.5, 30, 0),
    ("S05", "饮料", "罐装咖啡", 8., 3., 3., 30, 0),
    ("S06", "零食", "独立包装饼干", 5., 2., 2., 30, 0),
    ("S07", "零食", "坚果小袋", 9., 4., 4., 30, 0),
    ("S08", "零食", "薯片", 6., 2.5, 2.5, 30, 0),
    ("S09", "零食", "蛋白棒", 10., 5., 5., 30, 0),
    ("S10", "零食", "水果软糖", 4., 1.5, 1.5, 30, 0),
    ("S11", "配套用品", "免费取用的一次性勺叉，供购买餐食的顾客使用", 0., .2, 0., 30, 0),
    ("S12", "配套用品", "免费取用纸巾", 0., .05, 0., 30, 0),
]


def product_frame():
    return pd.DataFrame(PRODUCTS, columns=["sku", "category", "description", "price", "unit_cost", "salvage", "shelf_life_days", "includes_cutlery"])


def site_frame():
    return pd.DataFrame([{"site": f"C{i+1:02d}", "type": "办公楼", "microwave": int(i % 3 != 0),
                          "pantry_cutlery": int(i in (2, 5)), "opening_hours": OPENING_HOURS} for i in range(8)])


class OfficeWorld:
    def __init__(self, kind, seed, scenario_version=LEGACY_VERSION):
        if kind not in ("relationship", "confounding", "record_fault", "site_weekday"):
            raise ValueError("unknown private world")
        self.kind, self.seed = kind, seed
        if scenario_version not in (LEGACY_VERSION, REVISED_VERSION, EXTENDED_VERSION):
            raise ValueError('unknown scenario version')
        if kind == 'site_weekday' and scenario_version != EXTENDED_VERSION:
            raise ValueError('new private structure requires a new scenario version')
        self.scenario_version = scenario_version
        self.revised = scenario_version in (REVISED_VERSION, EXTENDED_VERSION)

    def support_plan(self, day, site):
        _, stock = self.day_context(day, site)
        paper = SUPPORT_STOCK_CAP
        if self.revised:
            rng = np.random.default_rng(np.random.SeedSequence([self.seed, day, int(site[1:])-1, 111]))
            paper = 0 if rng.random() < .3 else SUPPORT_STOCK_CAP
        return {'S11': stock, 'S12': paper}

    def support_plans(self, first_day, days):
        rows=[]
        for day in range(first_day, first_day+days):
            date=START+pd.Timedelta(days=day)
            if date.weekday()>=5:continue
            for site in site_frame().site:
                for sku,stock in self.support_plan(day,site).items():
                    rows.append({'day':day,'date':date.strftime('%Y-%m-%d'),'site':site,
                                 'support_sku':sku,'planned_opening_stock':stock,'known_at_hour':HOURS[0]})
        return pd.DataFrame(rows)

    def day_context(self, day, site):
        index = int(site[1:]) - 1
        rng = np.random.default_rng(np.random.SeedSequence([self.seed, day, index, 101]))
        low = rng.random() < .35
        traffic = (.58 if low else 1.12) * rng.lognormal(0, .11)
        missing = rng.random() < (.8 if low else .18) if self.kind == "confounding" else rng.random() < .4
        # Private generator only. The public task receives no label or target.
        # Vary one omitted interaction; retain stock plans and random streams.
        if self.kind == 'site_weekday' and (START + pd.Timedelta(days=day)).weekday() == 4:
            traffic *= {'C01': .55, 'C05': 1.45}.get(site, 1.)
        return traffic, (0 if missing else SUPPORT_STOCK_CAP)

    def features(self, first_day, days):
        rows = []
        products = product_frame().to_dict("records")
        for day in range(first_day, first_day + days):
            date = START + pd.Timedelta(days=day)
            if date.weekday() >= 5:
                continue
            for site in site_frame().to_dict("records"):
                _, aux = self.day_context(day, site["site"])
                plan=self.support_plan(day,site['site']) if self.revised else None
                for hour in HOURS:
                    for p in products[:10]:
                        row={"day": day, "date": date.strftime("%Y-%m-%d"), "weekday": date.weekday(),
                                     "hour": hour, "site": site["site"], "sku": p["sku"], "price": p["price"],
                                     "category": p["category"], "includes_cutlery": p["includes_cutlery"],
                                     "microwave": site["microwave"], "pantry_cutlery": site["pantry_cutlery"],
                                     "planned_s11_morning_stock": aux}
                        if self.revised:row['planned_s12_morning_stock']=plan['S12']
                        rows.append(row)
        return pd.DataFrame(rows)

    def generate(self, first_day, days, orders=None, assignment=None, support_sku="S11", main_high=False, corrected=False):
        rows, days_out = [], []
        products = product_frame().to_dict("records")
        assignment = assignment or {}
        for day in range(first_day, first_day + days):
            date = START + pd.Timedelta(days=day)
            if date.weekday() >= 5:
                continue
            for site in site_frame().to_dict("records"):
                si = int(site["site"][1:]) - 1
                traffic, aux = self.day_context(day, site["site"])
                inventory = {p["sku"]: (SUPPORT_STOCK_CAP if p["category"] == "配套用品" else historical_sale_stock(p["category"])) for p in products}
                inventory["S11"] = aux
                if self.revised:inventory.update(self.support_plan(day,site['site']))
                if main_high:
                    inventory.update({p['sku']:FRESH_TRIAL_OPENING for p in products if p['category']=='鲜食'})
                if orders is not None:
                    for p in products[:10]:
                        inventory[p["sku"]] = int(orders[(day, site["site"], p["sku"])])
                if assignment.get((day, site["site"]), 0):
                    inventory[support_sku] = SUPPORT_TRIAL_OPENING
                opening = inventory.copy()
                true_totals = {p["sku"]: 0 for p in products}
                for hour in HOURS:
                    start_aux = inventory["S11"]
                    support_start={p['sku']:inventory[p['sku']] for p in products[10:]}
                    aux_used = paper_used = 0
                    for pi, p in enumerate(products[:10]):
                        rng = np.random.default_rng(np.random.SeedSequence([self.seed, day, si, hour, pi, 201]))
                        base = (6.0 if 11 <= hour <= 13 else .8) if p["category"] == "鲜食" else (2.5 if 11 <= hour <= 14 else 1.4) * (1 - .045 * pi)
                        rate = base * (.83 + .065 * si) * traffic * (1. + .03 * date.weekday())
                        if self.kind == "relationship" and p["sku"] == "S01" and not site["pantry_cutlery"] and start_aux == 0:
                            rate *= np.exp(-1.05)
                        demand = int(rng.poisson(rate))
                        stock = inventory[p["sku"]]
                        sold = min(stock, demand)
                        inventory[p["sku"]] -= sold
                        true_totals[p["sku"]] += sold
                        available = 60 if inventory[p["sku"]] > 0 else (int(60 * rng.beta(stock, demand-stock+1)) if stock > 0 else 0)
                        recorded = sold
                        if self.kind == "record_fault" and si in (0, 1, 3, 6) and p["sku"] == "S01" and not corrected:
                            recorded = int(rng.binomial(sold, .62))
                        if p["sku"] == "S01" and not site["pantry_cutlery"]:
                            used = min(inventory["S11"], sold)
                            inventory["S11"] -= used
                            aux_used += used
                            true_totals["S11"] += used
                        if self.revised and p['category']=='鲜食':
                            issued=min(inventory['S12'],sold)
                            inventory['S12']-=issued;paper_used+=issued;true_totals['S12']+=issued
                        rows.append({"day": day, "date": date.strftime("%Y-%m-%d"), "weekday": date.weekday(), "hour": hour,
                                     "site": site["site"], "sku": p["sku"], "price": p["price"], "sales": recorded,
                                     "opening_stock": stock, "closing_stock": inventory[p["sku"]], "restock": 0,
                                     "available_minutes": available,
                                     "s11_hour_start_stock": start_aux, "treatment": assignment.get((day, site["site"]), 0)})
                    for p in products[10:]:
                        used = aux_used if p["sku"] == "S11" else paper_used
                        rows.append({"day": day, "date": date.strftime("%Y-%m-%d"), "weekday": date.weekday(), "hour": hour,
                                     "site": site["site"], "sku": p["sku"], "price": p["price"], "sales": used,
                                     "opening_stock": support_start[p['sku']],
                                     "closing_stock": inventory[p["sku"]], "restock": 0, "available_minutes": 60 if inventory[p["sku"]] > 0 else 0,
                                     "s11_hour_start_stock": start_aux, "treatment": assignment.get((day, site["site"]), 0)})
                profit = 0.
                waste = 0
                for p in products:
                    q, sold = opening[p["sku"]], true_totals[p["sku"]]
                    if p["category"] == "配套用品":
                        profit -= p["unit_cost"] * sold
                    else:
                        profit += p["price"] * sold - p["unit_cost"] * q + p["salvage"] * (q - sold)
                        if p["category"] == "鲜食":
                            waste += q - sold
                days_out.append({"day": day, "date": date.strftime("%Y-%m-%d"), "site": site["site"], "net_profit": profit,
                                 "fresh_waste": waste, "treatment": assignment.get((day, site["site"]), 0)})
        hourly=pd.DataFrame(rows)
        if self.revised:hourly=hourly.drop(columns='s11_hour_start_stock')
        return hourly, pd.DataFrame(days_out)

    def public_dataset(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        hourly, daily = self.generate(0, 84)
        products, sites = product_frame(), site_frame()
        with sqlite3.connect(directory / "business.sqlite") as db:
            for name, frame in (("hourly", hourly.drop(columns="treatment")), ("daily_finance", daily.drop(columns="treatment")),
                                ("products", products), ("sites", sites)):
                frame.to_sql(name, db, index=False, if_exists="replace")
        history = hourly.merge(products, on=["sku", "price"]).merge(sites.drop(columns=["type", "opening_hours"]), on="site")
        if self.revised:
            features=self.features(0,84)
            plan_columns=[c for c in features if c.startswith('planned_')]
            daily_plans=features[['day','site']+plan_columns].drop_duplicates()
            history=history.merge(daily_plans,on=['day','site'],validate='many_to_one')
            plans=self.support_plans(0,84)
            with sqlite3.connect(directory/'business.sqlite') as db:
                plans.to_sql('support_plans',db,index=False,if_exists='replace')
                features.to_sql('prediction_features',db,index=False,if_exists='replace')
            plans.to_csv(directory/'support_plans.csv',index=False)
            features.to_csv(directory/'prediction_features.csv',index=False)
        history.to_csv(directory / "history.csv", index=False)
        products.to_csv(directory / "products.csv", index=False)
        sites.to_csv(directory / "sites.csv", index=False)
        self.features(84, 14).to_csv(directory / "development_features.csv", index=False)
        return history


BASELINE_CODE = '''import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import PoissonRegressor

def predict(history, future):
    h = history[(history['day'] < 56) & (history['available_minutes'] == 60) & (history['category'] != '配套用品')]
    transform = ColumnTransformer([('cats', OneHotEncoder(handle_unknown='ignore'), ['site','sku','weekday','hour'])], remainder='drop')
    model = make_pipeline(transform, PoissonRegressor(alpha=.1, max_iter=300))
    model.fit(h, h['sales'])
    return np.maximum(0, model.predict(future))
'''

STRONG_CODE = '''import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import make_pipeline
from sklearn.ensemble import HistGradientBoostingRegressor

def predict(history, future):
    h = history[(history['day'] < 56) & (history['available_minutes'] == 60) & (history['category'] != '配套用品')]
    future = future.rename(columns={'planned_s11_morning_stock':'s11_hour_start_stock'})
    fields = ['site','sku','weekday','hour','price','includes_cutlery','microwave','pantry_cutlery','s11_hour_start_stock']
    h = h.copy()
    h['sales'] = h['opening_stock'] + h['restock'] - h['closing_stock']
    transform = ColumnTransformer([('cats', OneHotEncoder(handle_unknown='ignore', sparse_output=False), ['site','sku']), ('nums','passthrough',fields[2:])])
    model = make_pipeline(transform, HistGradientBoostingRegressor(loss='poisson', max_iter=150, max_leaf_nodes=15, l2_regularization=5, random_state=17))
    model.fit(h[fields], h['sales'])
    return np.maximum(0, model.predict(future[fields]))
'''


def operating_orders(features, predictions, *, with_trace=False):
    from ordering_policy import operating_orders as shared_orders
    return shared_orders(features, predictions, product_frame(), SALE_STOCK_CAP, with_trace=with_trace)


PUBLIC_TASK = """你们是办公售货柜经营公司的算法研究团队。现有系统分别预测商品销量并计算每日补货，使用柜点、商品、星期和时段。请从公开数据及业务资料定位反复出现的算法/数据/执行问题，提出竞争解释，做可复查验证，再决定是否修改算法。目标是提高净利润、减少鲜食报损，不能仅追求拟合。未知需求和客户偏好不可直接观测；销售会受库存限制。免费配套用品按实际发出量计成本。鲜食当天未售即报损；其他商品在本演示日评价按原成本回收剩余价值。每天开始补货，每SKU最多50件，无日内补货。所有数据是开发仿真，不是企业现场事实。
可查询12周历史。day<56用于估计，56<=day<84用于开发检验；最后独立验收另留数据。只允许用预测当时可知字段，不能用未来sales、closing_stock或available_minutes作预测特征。future.planned_s11_morning_stock是早晨知道的S11计划开库存，对将来时段持续可用仅是近似。history.s11_hour_start_stock始终是S11在该小时实际库存，即便当前行sku为S12；要分析某SKU自身的开库存，取该SKU行的opening_stock。
可申请库存账实核对，或最多2项新供给随机试验：每项14日历天，按柜点-日随机保证一个配套SKU开库存80件 vs 原操作，两组鲜食开库存均50件，价格和柜点条件不变。结果以真实供给、销售/库存回执为准；配套耗尽与主品断货必须报告。每项主终点为所列商品的柜点-日销量；alpha=.025，按柜点重复测量分析。新试验不是最终锁定评价。
原预测和predict输出的目标是每小时不受库存截断的需求均值，用于后续订货；不是给定历史实际库存后的记录销量。缺货时预测为正不自动意味着预测错误。原模型用全程有货行的销量近似估计需求，可能仍有选择偏差。算法接口：一个Python文件定义predict(history:DataFrame,future:DataFrame)->非负数组。不得读取future的目标结果，文件/网络权限另行限制。训练/开发/试验与算法版本的实际引用要保存。收益不足或错误解释可以修订或回退，允许合理未决。"""
