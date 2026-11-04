"""Validate the phase ablation before using common frozen-matrix execution."""
import json
from pathlib import Path

from freeze_discovery_tasks import PROJECT,launch_matrix


def launch(spec_path):
    spec_path=Path(spec_path).resolve();spec=json.loads(spec_path.read_text())
    if not spec_path.is_relative_to(PROJECT/"configs") or spec["strategies"] != ["numeric_full","native_control","confirmation_phase"]:raise ValueError("invalid phase specification")
    common={"use_state_brief":False,"use_reference_contract":True,"use_discovery_tasks":False}
    expected={"native_control":common|{"use_confirmation_phase":False},"confirmation_phase":common|{"use_confirmation_phase":True}}
    if spec["actor_features"]!=expected:raise ValueError("confounded public-phase comparison")
    if spec["scientific_checks"]!={"max_checks":6,"n_per_cohort":800,"total_alpha":.05,"tolerance":.05,"max_revisions":2}:raise ValueError("changed independent-check protocol")
    if spec["terminal_policy"]!="settle_committed" or not spec["no_scripted_LLM_warmup"]:raise ValueError("invalid entry or termination")
    if spec["primary_endpoint"]!="model_finishes_with_target_fit_and_final_candidate_independent_analysis_feedback_visible_before_finish_request":raise ValueError("incorrect feedback endpoint")
    return launch_matrix(spec_path,spec)


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("spec",type=Path)
    raise SystemExit(launch(parser.parse_args().spec))
