"""Numerically stable, origin-neutral ordering of executable models."""
import json
from lab import compile_expression


def program_size(model):
    expression=model["expression"]
    if isinstance(expression,str):
        variables={"heat","utensils","external_heat","external_utensils","items"}|(set(model["role_patterns"])-{"heating","utensils"})
        expression=compile_expression(expression,variables=variables)
    def size(node):
        return 1+sum(size(child) for child in node.get("args",[])) if isinstance(node,dict) else 1
    return size(expression)


def candidate_key(candidate,score="bic"):
    # Differences below 1e-8 are numerical ties, far below any inferential claim.
    # Do not let roundoff or LLM origin choose observationally tied extrapolations.
    return (round(candidate[score],8),program_size(candidate["model"]),
            candidate["terms"],json.dumps(candidate["model"],sort_keys=True,ensure_ascii=False))
