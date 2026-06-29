# smiles-ok-file  (contains only generic SMARTS substructure patterns)
"""
SMILES -> molecular features via RDKit.

RDKit provides physico-chemical descriptors only. It does NOT predict the ADME
parameters (CLint, fu,p, B:P, fu,inc) that drive the PK predictions - those must
be supplied as measured values or by a separate QSAR/ML model. RDKit also has no
native pKa predictor, so logD and ionisation class fall back to heuristics unless
provided by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

try:
    from rdkit import Chem
    from rdkit.Chem import Crippen, Descriptors, rdMolDescriptors
    _RDKIT_AVAILABLE = True
except Exception:  # pragma: no cover - import guard
    _RDKIT_AVAILABLE = False


@dataclass
class MoleculeFeatures:
    """Physico-chemical descriptors extracted from a single SMILES string."""
    smiles: str
    canonical_smiles: Optional[str] = None
    mw: Optional[float] = None          # g/mol
    clogp: Optional[float] = None       # Crippen logP
    logd: Optional[float] = None        # logD7.4 (== logP fallback if no pKa)
    tpsa: Optional[float] = None
    hbd: Optional[int] = None
    hba: Optional[int] = None
    rotatable_bonds: Optional[int] = None
    aromatic_rings: Optional[int] = None
    formal_charge: Optional[int] = None
    ionisation_class: Optional[str] = None   # 'acidic' | 'basic' | 'neutral'
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# SMARTS for a coarse ionisation-class heuristic (used only when class not supplied).
_ACID_SMARTS = [
    "[CX3](=O)[OX2H1]",          # carboxylic acid
    "[#16X4](=[OX1])(=[OX1])[OX2H1]",  # sulfonic acid
    "[PX4](=[OX1])([OX2H1])",    # phosphonic/phosphate -OH
    "c1[nH]nnn1",                # tetrazole
]
_BASE_SMARTS = [
    "[NX3;!$(N=O);!$(N-C=O);!$(N-S=O)]",  # aliphatic amine (excl. amide/sulfonamide)
    "[NX3]=[NX2]",                         # amidine-like
    "[nX3;H0;+0]",                         # basic aromatic N (approx.)
]


def _classify_ionisation(mol) -> str:
    """Very rough acid/base/neutral call from functional groups.

    This is a heuristic stand-in for a real pKa model. Supply `ionisation_class`
    explicitly whenever possible.
    """
    has_acid = any(mol.HasSubstructMatch(Chem.MolFromSmarts(s)) for s in _ACID_SMARTS)
    has_base = any(mol.HasSubstructMatch(Chem.MolFromSmarts(s)) for s in _BASE_SMARTS)
    if has_acid and not has_base:
        return "acidic"
    if has_base and not has_acid:
        return "basic"
    return "neutral"


def smiles_to_features(
    smiles: str,
    *,
    logd: Optional[float] = None,
    ionisation_class: Optional[str] = None,
) -> MoleculeFeatures:
    """Parse one SMILES string and return its descriptors.

    Never raises on a bad SMILES: returns a MoleculeFeatures with `.error` set so
    a batch run does not crash on a single bad input.

    Parameters
    ----------
    smiles : str
    logd : float, optional
        Measured/known logD7.4. If omitted, logD defaults to Crippen logP.
    ionisation_class : str, optional
        'acidic' | 'basic' | 'neutral'. If omitted, a SMARTS heuristic is used.
    """
    if not _RDKIT_AVAILABLE:
        return MoleculeFeatures(smiles=smiles, error="RDKit is not installed")

    if smiles is None or not isinstance(smiles, str) or not smiles.strip():
        return MoleculeFeatures(smiles=str(smiles), error="Empty or non-string SMILES")

    smiles = smiles.strip()
    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception as exc:  # extremely malformed input
        return MoleculeFeatures(smiles=smiles, error=f"RDKit parse exception: {exc}")

    if mol is None:
        return MoleculeFeatures(smiles=smiles, error="Unparseable SMILES (RDKit returned None)")

    try:
        clogp = float(Crippen.MolLogP(mol))
        cls = (ionisation_class or _classify_ionisation(mol)).strip().lower()
        feats = MoleculeFeatures(
            smiles=smiles,
            canonical_smiles=Chem.MolToSmiles(mol),
            mw=float(Descriptors.MolWt(mol)),
            clogp=clogp,
            logd=float(logd) if logd is not None else clogp,
            tpsa=float(rdMolDescriptors.CalcTPSA(mol)),
            hbd=int(rdMolDescriptors.CalcNumHBD(mol)),
            hba=int(rdMolDescriptors.CalcNumHBA(mol)),
            rotatable_bonds=int(rdMolDescriptors.CalcNumRotatableBonds(mol)),
            aromatic_rings=int(rdMolDescriptors.CalcNumAromaticRings(mol)),
            formal_charge=int(Chem.GetFormalCharge(mol)),
            ionisation_class=cls,
        )
        return feats
    except Exception as exc:  # descriptor failure on an otherwise-valid mol
        return MoleculeFeatures(smiles=smiles, error=f"Descriptor calculation failed: {exc}")
