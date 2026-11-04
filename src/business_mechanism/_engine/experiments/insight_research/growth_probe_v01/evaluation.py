"""Reference arithmetic and scoring fixtures, never supplied as Agent answers."""
import math
import numpy as np


def capacity_analysis(rows, threshold=2.):
    first = np.array([r['recorded_transactions'] for r in rows if r['capacity_multiplier'] == 1])
    second = np.array([r['recorded_transactions'] for r in rows if r['capacity_multiplier'] == 2])
    if min(len(first), len(second)) < 2:
        raise ValueError('both randomized groups need at least two windows')
    effect = float(second.mean() - first.mean())
    se = math.sqrt(float(first.var(ddof=1)/len(first) + second.var(ddof=1)/len(second)))
    # Diagnostic normal interval only; not a predeclared confirmation analysis.
    interval = [effect - 1.96*se, effect + 1.96*se]
    decision = 'supported' if interval[0] > threshold else 'refuted' if interval[1] < threshold else 'unresolved'
    return {'effect': effect, 'interval95_normal_diagnostic': interval, 'decision': decision,
            'units': 'recorded transactions/window, capacity2 minus capacity1', 'arm_windows': [len(first), len(second)]}


def reference_score(expected, declared):
    """Tiny three-way scoring facility test, not an overall research-quality metric."""
    allowed = {'supported', 'refuted', 'unresolved'}
    if expected not in allowed or declared not in allowed:
        raise ValueError('three-way expected and declared result required')
    return int(expected == declared)


def capture_analysis(rows, target=.9):
    """A finite operational proportion check; absent audits do not imply zero."""
    audited = [r for r in rows if 'completed' in r]
    total = sum(r['completed'] for r in audited)
    recorded = sum(r['recorded_transactions'] for r in audited)
    if not total:
        return {'decision':'unresolved','reason':'No completed-request denominator in received evidence',
                'completed_observations':0,'target':target}
    p = recorded / total; z = 1.96; denominator = 1+z*z/total
    center = (p+z*z/(2*total))/denominator
    radius = z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/denominator
    bounds = [center-radius,center+radius]
    decision = 'supported' if bounds[0] >= target else 'refuted' if bounds[1] < target else 'unresolved'
    return {'decision':decision,'recorded_fraction':p,'interval95_wilson':bounds,
            'completed_observations':total,'target':target,
            'scope':'Only the sampled windows under this fixed process; not an unrestricted causal mechanism certificate'}


def recorded_poisson_rate(world, capacity=1):
    return world.expected(capacity)
