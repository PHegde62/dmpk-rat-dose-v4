"""
Rough structure-based estimates for plasma protein binding (fu,p) and
blood:plasma ratio (B:P), for use ONLY when no measured or ML value exists.

⚠️  These are transparent, lipophilicity/charge-based PLACEHOLDERS — not validated
QSAR. They exist so the pipeline has a documented fallback and a clear hook to
swap in measured values or a Nucleus ML model. Erica flagged proper PPB and B:P
prediction as future work; treat outputs as order-of-magnitude only and prefer
measured / ML values. Every use is badged "est" in the app.
"""
from __future__ import annotations

from typing import Optional


def predict_fu_p(logd: Optional[float] = None, logp: Optional[float] = None) -> float:
    """Rough fu,p from lipophilicity (more lipophilic -> lower fu). PLACEHOLDER.

    Logistic in logD: ~0.7 at logD 0, ~0.1 at logD 3, ~0.02 at logD 4.5.
    """
    x = logd if logd is not None else (logp if logp is not None else 2.0)
    fu = 1.0 / (1.0 + 10 ** (0.6 * x - 0.4))
    return max(min(fu, 1.0), 1e-4)


def predict_blood_plasma_ratio(ionisation_class: Optional[str] = None) -> float:
    """Rough B:P by charge class (acids <1, bases >1, neutral ~1). PLACEHOLDER.

    In the absence of data, 1.0 is the standard assumption (per Erica); this only
    nudges by charge class as a starting guess.
    """
    return {"acidic": 0.7, "neutral": 1.0, "basic": 1.2}.get(
        (ionisation_class or "neutral").strip().lower(), 1.0)
