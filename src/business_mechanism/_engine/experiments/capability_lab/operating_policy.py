"""Public single-period assortment/newsvendor calculation, without a scorer."""
import itertools
import math

import numpy as np
from scipy.stats import binom


def validate_contract(contract):
    for key in ("customers_per_day","stock_capacity"):
        if type(contract[key]) is not int:raise ValueError("integer operating counts required")
    if not 1<=contract["customers_per_day"] or not 0<=contract["stock_capacity"]<=contract["customers_per_day"]:raise ValueError("invalid customer/stock capacity")
    if any(type(contract[key]) not in (int,float) or not math.isfinite(contract[key]) for key in ("retail_price","purchase_cost","salvage_value")):raise ValueError("finite public prices required")
    if not 0<=contract["salvage_value"]<=contract["purchase_cost"]<contract["retail_price"]:raise ValueError("invalid public newsvendor economics")
    if not contract["auxiliary_slot_profiles"] or any(type(slots) is not int or slots<0 for slots in contract["auxiliary_slot_profiles"]):raise ValueError("nonnegative integer material capacities required")


def profit_at_probability(p,q,material_cost,contract):
    n=contract["customers_per_day"]
    demand=np.arange(n+1)
    expected_sales=float(np.dot(np.minimum(demand,q),binom.pmf(demand,n,p)))
    return (contract["retail_price"]-contract["salvage_value"])*expected_sales-(contract["purchase_cost"]-contract["salvage_value"])*q-n*material_cost


def order_quantity(p,contract):
    fractile=(contract["retail_price"]-contract["purchase_cost"])/(contract["retail_price"]-contract["salvage_value"])
    return min(contract["stock_capacity"],int(binom.ppf(fractile,contract["customers_per_day"],p)))


def optimize(catalog,external,slots,probability,contract,quantity_function=order_quantity,profit_function=profit_at_probability):
    candidates=[]
    for size in range(slots+1):
        for combination in itertools.combinations(catalog,size):
            arm=[p["id"] for p in combination]
            cost=sum(p["retailer_cost_per_session"] for p in combination)
            p=probability(arm,external);q=quantity_function(p,contract)
            value=profit_function(p,q,cost,contract)
            candidates.append((value,-size,-cost,tuple(sorted(arm)),q,p,cost))
    value,_,_,arm,q,p,cost=max(candidates)
    return {"assortment":list(arm),"order_quantity":q,"predicted_probability":p,
            "predicted_expected_profit":value,"material_cost_per_session":cost}
