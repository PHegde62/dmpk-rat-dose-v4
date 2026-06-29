"""
Human PK profile simulation: one-compartment model with first-order oral
absorption and multiple (repeat) dosing, matching the Excel worksheet's
"Human PK Profile Simulations" panel.

Analytic superposition of single-dose oral curves:

    C_total(t) = sum_n  (F*Dose*ka)/(V*(ka-kel)) * (e^{-kel*(t-t_n)} - e^{-ka*(t-t_n)}),
                 over doses given at t_n = 0, tau, 2*tau, ... for t >= t_n

Free plasma concentration = C_total * fu_p. Concentrations are returned in nM.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_BW = 70.0  # kg


@dataclass
class SimResult:
    t_h: np.ndarray            # time (h)
    free_nM: np.ndarray        # free plasma concentration (nM)
    total_nM: np.ndarray       # total plasma concentration (nM)
    kel_per_h: float
    cmax_free: float
    cmin_free: float           # trough of the last full interval


def simulate_profile(
    *,
    dose_mg: float,
    mw: float,
    bioavailability_pct: float,
    ka_per_h: float,
    cl_plasma_mL_min_kg: float,
    vd_L_kg: float,
    tau_h: float,
    fu_p: float = 1.0,
    bw_kg: float = _BW,
    t_end_h: float = 96.0,
    dt_h: float = 0.1,
) -> SimResult:
    """Simulate a multiple-dose oral PK profile and return free/total nM vs time."""
    cl_L_h = cl_plasma_mL_min_kg * 60.0 / 1000.0 * bw_kg   # mL/min/kg -> L/h (whole body)
    v_L = vd_L_kg * bw_kg
    kel = cl_L_h / v_L
    F = bioavailability_pct / 100.0
    dose_nmol = dose_mg / mw * 1e6                          # mg / (g/mol) -> nmol

    t = np.arange(0.0, t_end_h + dt_h, dt_h)
    total = np.zeros_like(t)

    n_doses = int(t_end_h // tau_h) + 1
    ka = ka_per_h
    for n in range(n_doses):
        tn = n * tau_h
        m = t >= tn
        dts = t[m] - tn
        if abs(ka - kel) < 1e-9:  # avoid divide-by-zero (flip-flop edge)
            contrib = (F * dose_nmol / v_L) * kel * dts * np.exp(-kel * dts)
        else:
            contrib = (F * dose_nmol * ka) / (v_L * (ka - kel)) * \
                      (np.exp(-kel * dts) - np.exp(-ka * dts))
        total[m] += contrib

    free = total * fu_p

    # Cmax over whole profile; Cmin = trough at the start of the last full interval
    last_dose_t = (n_doses - 1) * tau_h
    trough_t = last_dose_t  # concentration just before the last dose ~ steady-state trough
    idx = int(np.argmin(np.abs(t - trough_t)))
    return SimResult(
        t_h=t, free_nM=free, total_nM=total, kel_per_h=kel,
        cmax_free=float(free.max()),
        cmin_free=float(free[idx]),
    )
