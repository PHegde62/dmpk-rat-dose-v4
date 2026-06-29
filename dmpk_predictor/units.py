"""
Unit-conversion module.

A registry-based converter that standardises heterogeneous experimental ADME
inputs to canonical internal units before any PK math runs. Adding a new unit is
a one-line registry entry (linear units) or a small handler (context-dependent
units such as CLint that need scaling factors, or solubility that needs MW).

Canonical internal units
-------------------------
    CLint        -> mL/min/kg   (whole-liver intrinsic clearance)
    permeability -> cm/s
    solubility   -> uM
    fu (unbound) -> fraction (0-1)
    efflux ratio -> unitless

Physically-impossible inputs raise ``UnitError`` (and are logged).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("dmpk_predictor.units")


class UnitError(ValueError):
    """Raised for unknown units or physically impossible values."""


# --------------------------------------------------------------------------- #
# Scaling factors used ONLY to collapse in vitro CLint -> mL/min/kg.
# Defaults follow the values requested in the brief (human liver).
# Note: these differ from config.PHYSIOLOGY (used by the per-species well-stirred
# model); keep them here so the two roles stay independent and explicit.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ScalingFactors:
    liver_weight_g_per_kg: float = 20.0   # g liver / kg body weight
    mppgl_mg_per_g: float = 45.0          # mg microsomal protein / g liver
    hpgl_1e6_per_g: float = 135.0         # 1e6 hepatocytes / g liver


DEFAULT_SCALING = ScalingFactors()


def scaling_for_species(species: str) -> "ScalingFactors":
    """Build CLint->mL/min/kg scaling factors from config.PHYSIOLOGY for a species.

    Used by the V4 rat path so in vitro CLint is scaled with RAT liver weight
    (40 g/kg), MPPGL (45 mg/g) and hepatocellularity (117e6 cells/g) instead of
    the human defaults.
    """
    from .config import PHYSIOLOGY
    phys = PHYSIOLOGY[species.strip().lower()]
    return ScalingFactors(
        liver_weight_g_per_kg=phys.lw_per_bw,
        mppgl_mg_per_g=phys.mppgl,
        hpgl_1e6_per_g=phys.hpgl,
    )


# Convenience constant for the V4 default target species (rat).
RAT_SCALING = ScalingFactors(liver_weight_g_per_kg=40.0, mppgl_mg_per_g=45.0,
                             hpgl_1e6_per_g=117.0)


# --------------------------------------------------------------------------- #
# Linear registries: value_canonical = value * factor
# --------------------------------------------------------------------------- #
_LINEAR_REGISTRY: dict[str, dict[str, float]] = {
    # canonical: cm/s
    "permeability": {
        "cm/s": 1.0,
        "1e-6 cm/s": 1e-6, "e-6 cm/s": 1e-6, "10^-6 cm/s": 1e-6, "1e-6cm/s": 1e-6,
        "nm/s": 1e-7,          # 1 nm/s = 1e-7 cm/s
    },
}


def register_linear_unit(quantity: str, unit: str, factor_to_canonical: float) -> None:
    """Extend the linear registry at runtime."""
    _LINEAR_REGISTRY.setdefault(quantity, {})[unit.strip().lower()] = factor_to_canonical


def _linear(quantity: str, value: float, unit: str) -> float:
    table = _LINEAR_REGISTRY.get(quantity, {})
    key = unit.strip().lower()
    if key not in table:
        raise UnitError(f"Unknown {quantity} unit: {unit!r}. Known: {sorted(table)}")
    return value * table[key]


# --------------------------------------------------------------------------- #
# Context-dependent / non-linear conversions
# --------------------------------------------------------------------------- #
def convert_fu(value: float, unit: str) -> float:
    """Plasma protein binding -> fraction unbound (0-1)."""
    u = unit.strip().lower()
    if u in ("fraction", "fu", "frac", "unitless", ""):
        fu = float(value)
    elif u in ("% bound", "%bound", "percent bound", "pct bound", "pb%", "%pb"):
        if not 0.0 <= value <= 100.0:
            raise UnitError(f"% bound must be 0-100, got {value}")
        fu = 1.0 - value / 100.0
    elif u in ("% unbound", "%unbound", "percent unbound"):
        if not 0.0 <= value <= 100.0:
            raise UnitError(f"% unbound must be 0-100, got {value}")
        fu = value / 100.0
    else:
        raise UnitError(f"Unknown fu unit: {unit!r}")
    if not 0.0 < fu <= 1.0:
        raise UnitError(f"fraction unbound must be in (0, 1], got {fu}")
    return fu


def convert_solubility(value: float, unit: str, mw: float | None) -> float:
    """Solubility -> uM. ug/mL and mg/mL require molecular weight (g/mol)."""
    if value < 0:
        raise UnitError(f"Solubility cannot be negative, got {value}")
    u = unit.strip().lower()
    if u in ("um", "µm", "umol/l", "µmol/l"):
        return float(value)
    if u in ("ug/ml", "µg/ml", "mg/l"):
        if not mw:
            raise UnitError("MW required to convert ug/mL -> uM")
        return value * 1000.0 / mw
    if u in ("mg/ml", "g/l"):
        if not mw:
            raise UnitError("MW required to convert mg/mL -> uM")
        return value * 1e6 / mw
    raise UnitError(f"Unknown solubility unit: {unit!r}")


def convert_clint(
    value: float,
    unit: str,
    matrix: str,
    scaling: ScalingFactors = DEFAULT_SCALING,
) -> float:
    """Intrinsic clearance -> mL/min/kg (whole liver).

    uL/min/mg protein    : value * MPPGL * LW / 1000
    uL/min/1e6 cells     : value * HPGL  * LW / 1000
    mL/min/kg            : identity (already whole-liver scaled)
    """
    if value < 0:
        raise UnitError(f"CLint cannot be negative, got {value}")
    u = unit.strip().lower().replace(" ", "")
    lw = scaling.liver_weight_g_per_kg
    if u in ("ml/min/kg", "mlmin-1kg-1"):
        return float(value)
    if u in ("ul/min/mg", "µl/min/mg", "ul/min/mgprotein"):
        return value * scaling.mppgl_mg_per_g * lw / 1000.0
    if u in ("ul/min/10^6cells", "ul/min/1e6cells", "µl/min/10^6cells",
             "ul/min/millioncells", "ul/min/10e6cells"):
        return value * scaling.hpgl_1e6_per_g * lw / 1000.0
    raise UnitError(f"Unknown CLint unit: {unit!r} (matrix={matrix})")


def convert_efflux_ratio(value: float) -> float:
    if value <= 0:
        raise UnitError(f"Efflux ratio must be > 0, got {value}")
    return float(value)
