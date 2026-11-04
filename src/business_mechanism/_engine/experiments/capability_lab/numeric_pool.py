"""Candidate inference from public facts and verified cohorts only."""
import math

from model_order import candidate_key
from symbolic import search


def numeric_pool(evidence,patterns,expanded=True,beam=3,max_terms=4,committee_size=48):
    candidates=[]
    for link in ("linear","logit"):
        candidates+=search(evidence,patterns,expanded=expanded,beam=beam,max_terms=max_terms,
            link=link,public_dedup=True,interaction_order=4,preserve_aliases=True,max_candidates=32)
    n=sum(r["n"] for r,_ in evidence.verified_observations())
    for row in candidates:
        row["bic"]=row["deviance"]+row["rank"]*math.log(n)
        row["origin"]="numeric_search"
    candidates.sort(key=candidate_key)
    return candidates[:committee_size]
