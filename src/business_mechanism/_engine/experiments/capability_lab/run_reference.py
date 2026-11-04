"""Environment certification and public-information scripted comparisons."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from lab import ResearchLab, World, factorial_expression, model_with, op, private_score, var


def role_ids(public):
    heat = next(p["id"] for p in public["catalog"] if "加热" in p["description"] and "餐具" not in p["description"])
    utensils = next(p["id"] for p in public["catalog"] if "餐具" in p["description"] and "加热" not in p["description"])
    return heat, utensils


def run_baseline(world, strategy, n=400):
    lab = ResearchLab(world)
    public = lab.public()
    # Both baselines use legal measurements, not private fault labels.
    audit = lab.call("audit", {})
    reconcile = lab.call("reconcile", {})
    verified_supply = audit["physical_opening"] != audit["recorded_opening"]
    verified_meter = reconcile["recorded_sales"] != reconcile["verified_sales"]
    h, u = role_ids(public)
    table = {}
    cells = [(0, 0), (1, 0), (0, 1)] if strategy == "one_at_a_time" else [(0, 0), (1, 0), (0, 1), (1, 1)]
    for a, b in cells:
        assortment = ([h] if a else []) + ([u] if b else [])
        r = lab.call("experiment", {"assortment": assortment, "site": "00", "stage": "source",
                                    "n": n, "verified_supply": verified_supply, "verified_meter": verified_meter,
                                    "prediction": 0.3, "rationale": "固定、同信息的角色因子对照"})
        table[a, b] = r["observed_rate"]
    if strategy == "one_at_a_time":
        table[1, 1] = table[1, 0] + table[0, 1] - table[0, 0]
    expr = factorial_expression(table, include_external=strategy != "unsafe_transfer")
    if strategy == "full_context_factorial":
        # A strong comparator observes every site × role combination. Distinct
        # external strata are separately fitted; external equivalence is not assumed.
        adaptation = lab.call("open_transfer", {})
        ah, au = role_ids(adaptation)
        all_tables = {"00": table}
        for site in ["10", "01", "11"]:
            t = {}
            for a, b in [(0, 0), (1, 0), (0, 1), (1, 1)]:
                r = lab.call("experiment", {"assortment": ([ah] if a else []) + ([au] if b else []),
                                            "site": site, "stage": "adaptation", "n": n,
                                            "verified_supply": verified_supply, "verified_meter": verified_meter,
                                            "prediction": 0.3, "rationale": "固定全上下文析因；不从私人世界取信息"})
                t[a, b] = r["observed_rate"]
            all_tables[site] = t
        eh, eu = var("external_heat"), var("external_utensils")
        terms = []
        for site, t in all_tables.items():
            a, b = map(int, site)
            weight = op("mul", eh if a else op("sub", 1, eh), eu if b else op("sub", 1, eu))
            terms.append(op("mul", weight, factorial_expression(t, include_external=False)))
        expr = op("add", *terms)
    lab.call("finish", {"model": model_with(expr),
                        "claims": "固定公开事实匹配与析因估计；未检查额外陈列商品造成的效应；不推断心理中介。"})
    return private_score(lab)


def certify(seed=0):
    """Analytical identifiability check, not claimed agent evidence."""
    worlds = [World(seed, f) for f in ["complement", "independent", "substitute", "crowding", "null"]]
    h, u = role_ids(ResearchLab(worlds[0]).public())
    d = next(p["id"] for p in worlds[0].catalogs["source"] if "饮用水" in p["description"])
    designs = [[], [h], [u], [h, u], [h, u, d]]
    signatures = {w.family: [w.probability("source", arm, (0, 0)) for arm in designs] for w in worlds}
    histories = [ResearchLab(w).public()["history"] for w in worlds]
    assert all(history == histories[0] for history in histories)
    assert len({tuple(s) for s in signatures.values()}) == len(worlds)
    # Identical OAT signatures for AND interaction, crowding and null establish
    # a structural failure of OAT, even with infinitely precise cell means.
    assert signatures["complement"][:3] == signatures["null"][:3]
    assert signatures["complement"][:3] == signatures["crowding"][:3]
    return {"matched_histories": True, "designs": ["empty", "heat", "utensils", "both", "both+water"],
            "private_signatures": signatures,
            "interpretation": "five worlds separable with five legal cells; OAT cannot separate complement/crowding/null"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "results" / "reference.json")
    args = ap.parse_args()
    rows = []
    for family in ["complement", "independent", "substitute", "crowding", "null"]:
        for strategy in ["one_at_a_time", "unsafe_transfer", "role_factorial", "full_context_factorial"]:
            for seed in range(args.seeds):
                score = run_baseline(World(seed, family), strategy)
                rows.append({"seed": seed, "family": family, "strategy": strategy, **score})
    summary = []
    for family in ["complement", "independent", "substitute", "crowding", "null"]:
        for strategy in ["one_at_a_time", "unsafe_transfer", "role_factorial", "full_context_factorial"]:
            group = [r for r in rows if r["family"] == family and r["strategy"] == strategy]
            summary.append({"family": family, "strategy": strategy,
                            **{k: round(float(np.mean([r[k] for r in group])), 6)
                               for k in ["source_probability_rmse", "heldout_probability_rmse", "heldout_effect_rmse"]},
                            "mean_sessions": float(np.mean([r["used"]["sessions"] for r in group]))})
    diagnosis = []
    for fault in ["none", "supply", "report"]:
        lab = ResearchLab(World(0, "null", fault))
        diagnosis.append({"private_fault": fault, "public_history": lab.public()["history"][0],
                          "audit": lab.call("audit", {}), "reconcile": lab.call("reconcile", {})})
    result = {"certification": certify(), "diagnosis_fixtures": diagnosis,
              "seeds_per_cell": args.seeds, "summary": summary, "rows": rows,
              "limitations": "scripted development results; no LLM system comparison, no cluster effects, no recurrent inventory dynamics"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.out), "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
