"""Paired development accounting; repeated worlds are never extra samples."""
from collections import Counter
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def load(phase,seed,family,profile,strategy):
    return json.loads((ROOT/"results"/phase/f"{strategy}_{family}_{profile}_s{seed}.json").read_text())


def registrations(r):
    return [(e["available_at"],{k:e["payload"]["plan"]["action"][k] for k in ("stage","site","assortment","n","prediction")}) for e in r["events"] if e["kind"]=="plan_registered"]


def final_measurements(r):
    return Counter(json.dumps({k:x[k] for k in ("stage","site","assortment","n","observed_sales","verified_supply","verified_meter")},sort_keys=True) for x in r["public_final_state"]["mature_evidence"])


def compare():
    prefixes=[];repairs=[];pilots=[]
    wide="development_temporal_v01_20261012";tight="development_temporal_deadline_v01_20261012"
    for seed in (3701,3702):
        for family in ("threeway","mixed_scope"):
            for profile in ("staggered","interruptions"):
                for strategy in ("numeric_serial","numeric_async"):
                    a=load(wide,seed,family,profile,strategy);b=load(tight,seed,family,profile,strategy)
                    rb=registrations(b);ra=registrations(a)
                    def receipts(r):return [e["payload"] for e in r["events"] if e["kind"] in {"measurement_received","measurement_revised"} and e["available_at"]<=50]
                    prefixes.append({"seed":seed,"family":family,"profile":profile,"strategy":strategy,
                        "launch_prefix_identical":rb==ra[:len(rb)],"available_receipts_identical_until_cutoff":receipts(a)==receipts(b),
                        "tight_status":b["status"],"tight_checks":len(b["confirmations"]),"tight_sessions":b["used"]["sessions"]})
            for strategy in ("numeric_serial","numeric_async"):
                a=load(wide,seed,family,"staggered",strategy);b=load(wide,seed,family,"interruptions",strategy)
                repairs.append({"seed":seed,"family":family,"strategy":strategy,"final_verified_measurement_multisets_equal":final_measurements(a)==final_measurements(b),
                    "additional_repair_cost":b["used"]["cost"]-a["used"]["cost"],"additional_calendar_ticks":b["used"]["logical_time"]-a["used"]["logical_time"]})
    for phase in ("development_temporal_coordinator_v01_20261012","development_temporal_coordinator_v02_20261012"):
        for family in ("threeway","mixed_scope"):
            a=load(phase,3703,family,"interruptions","numeric_async");b=load(phase,3703,family,"interruptions","llm_async_coordinator")
            pilots.append({"phase":phase,"seed":3703,"family":family,"final_verified_measurement_multisets_equal":final_measurements(a)==final_measurements(b),
                "numeric_clock":a["used"]["logical_time"],"llm_clock":b["used"]["logical_time"],
                "effect_rmse_difference":b["private_score"]["heldout_effect_rmse"]-a["private_score"]["heldout_effect_rmse"],
                "regret_difference":b["private_score"]["mean_expected_operating_regret_per_customer"]-a["private_score"]["mean_expected_operating_regret_per_customer"],
                "api_call_phases":dict(Counter(c["scientific_phase"] for c in b["model_calls"])),
                "invalid_submissions":sum("submission_error" in c or "error" in c for c in b["model_calls"]),
                "same_final_ast":a["frozen_final"]["model"]==b["frozen_final"]["model"]})
    return {"deadline_prefix_checks":prefixes,"repair_pairs":repairs,"pilot_pairs":pilots,
        "all_prefix_checks_passed":all(r["launch_prefix_identical"] and r["available_receipts_identical_until_cutoff"] for r in prefixes),
        "interpretation":"After-run development comparison. Two seeds for serial/async and one shared seed for coordinator pilots. Exact shared measurement multisets are not independent evidence. Tiny AST coefficient roundoff is retained, not normalized away. No task-level significance claim."}


if __name__=="__main__":
    result=compare();path=ROOT/"results/setup_deepseek_20261012/temporal-paired-comparisons-v02.json"
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"all_prefix_checks_passed":result["all_prefix_checks_passed"],"prefixes":len(result["deadline_prefix_checks"]),"repair_pairs":result["repair_pairs"],"pilot_pairs":result["pilot_pairs"]},ensure_ascii=False,indent=2))
