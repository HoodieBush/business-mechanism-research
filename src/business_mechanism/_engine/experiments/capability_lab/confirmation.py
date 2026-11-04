"""Exact fresh-cohort checks with a bounded, task-wise simultaneous error rule."""
from scipy.stats import beta
from scipy.stats import binom
import numpy as np


def assess(k,n,frozen_prediction,tolerance=.05,total_alpha=.05,max_checks=4):
    alpha=total_alpha/max_checks
    lower=0. if k==0 else float(beta.ppf(alpha/2,k,n-k+1))
    upper=1. if k==n else float(beta.ppf(1-alpha/2,k+1,n-k))
    band=(max(0.,frozen_prediction-tolerance),min(1.,frozen_prediction+tolerance))
    if upper<band[0] or lower>band[1]:state="contradicted"
    elif lower>=band[0] and upper<=band[1]:state="supported_within_tolerance"
    else:state="inconclusive"
    return {"state":state,"count":k,"n":n,"frozen_prediction":frozen_prediction,
        "exact_probability_interval":[lower,upper],"prediction_tolerance_band":list(band),
        "total_alpha":total_alpha,"max_checks":max_checks,"per_check_alpha":alpha,
        "scope":"本次新 cohort 的条件；不证明候选唯一、心理中介或所有未测配置。"}


def exact_check_power(true_probability,frozen_prediction,n,tolerance=.05,total_alpha=.05,max_checks=4):
    """Offline binomial enumeration, not an observed-data stopping rule."""
    k=np.arange(n+1);alpha=total_alpha/max_checks
    lower=np.zeros(n+1);upper=np.ones(n+1)
    lower[1:]=beta.ppf(alpha/2,k[1:],n-k[1:]+1)
    upper[:-1]=beta.ppf(1-alpha/2,k[:-1]+1,n-k[:-1])
    lo=max(0.,frozen_prediction-tolerance);hi=min(1.,frozen_prediction+tolerance)
    supported=(lower>=lo)&(upper<=hi)
    contradicted=(upper<lo)|(lower>hi)
    mass=binom.pmf(k,n,true_probability)
    return {"true_probability":true_probability,"frozen_prediction":frozen_prediction,"n":n,
        "tolerance":tolerance,"total_alpha":total_alpha,"max_checks":max_checks,
        "supported_within_tolerance":float(mass[supported].sum()),
        "contradicted":float(mass[contradicted].sum()),
        "inconclusive":float(mass[~(supported|contradicted)].sum())}
