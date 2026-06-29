# smiles-ok-file  (contains only public reference SMILES)
"""
DMPK Human Dose Predictor — two modules over one engine.

  • Post-synthesis : measured/preliminary data, auto-filled from CDD Vault.
  • Pre-synthesis  : ML predictions auto-filled from Nucleus (by SMILES).

Both share the worksheet engine: per-species inputs, in-vivo (allometry) and
in-vitro (well-stirred IVIVE) human CL, a selectable Vdss method
(animal single-species · Øie–Tozer · Nucleus ML), AUC/Cmin/Cmax dosing, and a
multiple-dose concentration-time plot. Inputs are badged by source
(green ✓ = from CDD/Nucleus, red NA = not reported, amber = default) and a
worksheet-style Excel report can be downloaded.

Run:  pip install -r requirements.txt   then   streamlit run app.py
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import streamlit as st

from dmpk_predictor import units
from dmpk_predictor.allometry import scale_single_species, multi_species_allometry
from dmpk_predictor.ivive import predict_hepatic_cl
from dmpk_predictor import binding
from dmpk_predictor.config import PHYSIOLOGY
from dmpk_predictor.dose import predict_dose
from dmpk_predictor.simulate import simulate_profile
from dmpk_predictor.vd_predict import predict_vd
from dmpk_predictor.bioavailability import predict_bioavailability
from dmpk_predictor import props
from dmpk_predictor.features import smiles_to_features
from dmpk_predictor.export import results_to_excel_bytes, worksheet_report_bytes
from dmpk_predictor.pipeline import run_table
from dmpk_predictor.cdd_client import fetch_adme_from_cdd, CDDError
from dmpk_predictor.cdd_config import CDDSettings
from dmpk_predictor.nucleus_screen import load_screen_csv, screen_row_to_inputs

st.set_page_config(page_title="DMPK Human Dose Predictor", page_icon="💊", layout="wide")
ANIMALS = ["mouse", "rat", "dog", "cyno"]
ENGINE2WS = {"clint": "clint_mic", "fu_inc": "fu_mic", "fu_p": "fu_human",
             "blood_plasma_ratio": "bp", "permeability": "papp", "solubility": "sol",
             "clint_hep": "clint_hep", "fu_hep": "fu_hep", "logd_meas": "logd"}


@st.cache_data(show_spinner=False, ttl=3600)
def _cached_fetch(ident: str, is_smiles: bool, vault: str, token: str, agg: str):
    """Cache CDD fetches for an hour so re-running the same compound — or any UI
    rerun — is instant instead of re-querying the (slow) CDD API."""
    return fetch_adme_from_cdd(
        ident, is_smiles=is_smiles,
        settings=CDDSettings(vault_id=vault, token=token, aggregation=agg))


def pf(key, default):
    return st.session_state.get("pf", {}).get(key, default)


def badge(field: str) -> str:
    src = st.session_state.get("src", {})
    miss = st.session_state.get("missing", set())
    name = st.session_state.get("source_name", "src")
    if field in src:
        return f"  :green[✓{name}]"
    if st.session_state.get("fetched") and field in miss:
        return "  :red[NA]"
    return "  :orange[default]"


def source_of(field: str, value) -> str:
    src = st.session_state.get("src", {})
    miss = st.session_state.get("missing", set())
    name = st.session_state.get("source_name", "source")
    if field in src:
        try:
            return "manual" if abs(float(value) - float(src[field])) > 1e-9 else name
        except (TypeError, ValueError):
            return name
    if st.session_state.get("fetched") and field in miss:
        return "NA" if (not value) else "manual"
    return "manual" if value else "default"


# --------------------------------------------------------------------------- #
# Sidebar — data-source credentials + scaling factors
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("CDD Vault")
    cdd_vault = st.text_input("Vault ID", value=os.environ.get("CDD_VAULT_ID", ""))
    cdd_token = st.text_input("CDD API token", type="password", value=os.environ.get("CDD_TOKEN", ""))
    cdd_agg = st.selectbox("Multi-study aggregation", ["mean", "geomean", "median", "latest"],
                           index=0, help="How to combine repeat CDD studies for one readout.")
    st.caption("Pre-synthesis (ML): use the **Pre-synthesis** module and upload a Nucleus "
               "Virtual Screen CSV export — no token needed.")
    st.divider()
    st.header("CLint → mL/min/kg scaling")
    lw = st.number_input("Liver weight (g/kg)", value=20.0)
    mppgl = st.number_input("MPPGL (mg/g)", value=45.0)
    hpgl = st.number_input("HPGL (1e6 cells/g)", value=135.0)
scaling = units.ScalingFactors(liver_weight_g_per_kg=lw, mppgl_mg_per_g=mppgl, hpgl_1e6_per_g=hpgl)

st.title("💊 DMPK Human Dose Predictor")
mode = st.radio("Module", ["🧪 Post-synthesis (measured · CDD)",
                           "🔮 Pre-synthesis (Nucleus CSV)",
                           "🤖 Pre-synthesis (ML · SMILES)"],
                horizontal=True)

# New V2 ML module: predict CL/Vss/fup from a SMILES with the D-MPNN ensemble,
# then project a dose. Rendered by models/presynth_ml_ui.py; V1 paths untouched.
if mode.startswith("🤖"):
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "models"))
    import presynth_ml_ui
    presynth_ml_ui.render()
    st.stop()

is_pre = mode.startswith("🔮")
st.caption("Source badges:  :green[✓CDD/Nucleus] from data   ·   :red[NA] not reported   ·   "
           ":orange[default] placeholder (edit any field to override).")

ASSUMPTIONS = [
    "**Free-concentration basis:** all targets (Css,max/AUC/Css,trough) are *free* plasma "
    "concentrations; protein binding (fu,p) drives the result (total = free / fu,p).",
    "**Hepatic clearance only:** microsome/hepatocyte predictions assume hepatic metabolism is "
    "the primary clearance route — no renal, biliary, extrahepatic, or transporter-mediated CL. "
    "Check IVIVE for each program.",
    "**Well-stirred liver model** with steady-state assumptions; CLh = Qh·fu,b·CLu,int/(Qh+fu,b·CLu,int).",
    "**Dose math assumes ka ≫ kel** (absorption much faster than elimination); outputs are "
    "maintenance doses to hold the target at steady state.",
    "**PK profile** is a one-compartment, first-order-absorption *estimate* — not full "
    "compartmental/PBPK modelling & simulation.",
    "**Bioavailability** F = Fa·Fg·Fh, with Fg ≈ 1, Fh = 1 − CLh,blood/Qh, and Fa from permeability "
    "with optional BCS-class solubility caps (class 2/4 absorption-limited).",
    "**Blood:plasma ratio assumed 1.0** when not measured.",
    "**Vdss** is chosen per method: animal single-species (fu-corrected, exponent 0.75), Øie–Tozer "
    "(needs tissue fu,t), or ML — no measured tissue binding.",
    "**Covalent / irreversible inhibitors:** the reversible well-stirred CL and steady-state "
    "assumptions do not apply — use kinact/KI or target-turnover methods.",
    "**Structure-based fu,p / B:P** are rough placeholder QSARs — prefer measured or Nucleus ML values.",
    "**Program-specific validity:** IVIVE/allometry success varies by program; confirm the method "
    "is reasonable for the chemotype before trusting the dose.",
    "**Physiology constants** (Qh, liver weight, MPPGL, HPGL, 70 kg BW) are standard human values; "
    "adjust in the sidebar if needed.",
]
with st.expander("ℹ️ Assumptions & limitations — read before using a prediction"):
    for a in ASSUMPTIONS:
        st.markdown("- " + a)

tab_ws, tab_batch = st.tabs(["Worksheet", "Batch upload"])
cl_iv = vd_iv = dose_iv = cl_vitro = dose_vitro = None
vd_pred = None

with tab_ws:
    # ---- Auto-fill: CDD (post-synthesis) or Nucleus Virtual Screen CSV (pre-synthesis) ----
    if is_pre:
        with st.expander("⚡ Auto-fill from Nucleus Virtual Screen export (CSV)", expanded=True):
            st.caption("In GEMS: create an ADME Virtual Screen for your SMILES → open the results → "
                       "**Download CSV**, then upload it here. The ML models output human CL directly "
                       "(mL/min/kg); Vdss isn't predicted, so use Øie–Tozer or animal scaling.")
            vs_file = st.file_uploader("Virtual Screen results (.csv/.xlsx)", type=["csv", "xlsx"], key="vs_up")
            if vs_file is not None:
                raw = (pd.read_csv(vs_file) if vs_file.name.lower().endswith(".csv")
                       else pd.read_excel(vs_file))
                raw, colmap = load_screen_csv(raw)
                st.caption("Mapped: " + (", ".join(f"{k}→{v}" for k, v in colmap.items()) or "nothing"))
                name_col = colmap.get("name")
                labels = (raw[name_col].astype(str).tolist() if name_col
                          else [f"row {i}" for i in range(len(raw))])
                idx = st.selectbox("Compound", list(range(len(raw))), format_func=lambda i: labels[i])
                if st.button("Use this compound"):
                    p = screen_row_to_inputs(raw.iloc[idx].to_dict(), colmap)
                    src = {k: p[k] for k in ("mw", "logd", "fu_human", "papp", "sol", "cl_direct") if k in p}
                    st.session_state.update(pf=p, src=src, missing=set(), fetched=True, source_name="Nucleus")
                    st.success(f"Loaded {p.get('id', 'compound')} from Virtual Screen "
                               f"({len(src)} predicted fields)")
                    st.rerun()
    else:
        with st.expander("⚡ Auto-fill from CDD Vault (GEN-ID or SMILES)", expanded=False):
            ident = st.text_input("GEN-ID or SMILES", key="ws_ident")
            kind = st.radio("Identifier", ["GEN-ID", "SMILES"], horizontal=True, key="ws_kind")
            if st.button("Fetch"):
                try:
                    p, src, miss = {}, {}, set()
                    adme, prov = _cached_fetch(
                        ident.strip(), (kind == "SMILES"), cdd_vault, cdd_token, cdd_agg)
                    p["id"] = prov.get("molecule_name") or ident.strip()
                    smi = ident.strip() if kind == "SMILES" else prov.get("smiles")
                    if smi:
                        p["smiles"] = smi
                    for sp, d in adme.get("invivo", {}).items():
                        for m in ("cl", "vd", "fu"):
                            if m in d:
                                p[f"{m}_{sp}"] = d[m]
                        if "F" in d:                       # oral bioavailability %
                            p[f"F_{sp}"] = d["F"]
                    found, missing = prov["found"], prov["missing"]
                    if smi:
                        feats = smiles_to_features(smi)
                        if not feats.error:
                            p.setdefault("mw", feats.mw)
                            p.setdefault("logd", feats.logd)
                            p["clogp"] = feats.clogp
                            p.setdefault("class", feats.ionisation_class)
                            src["mw"] = p["mw"]
                    if "clint" in adme:
                        p["clint_mic"] = adme["clint"]["value"]
                    if "fu_inc" in adme:
                        p["fu_mic"] = adme["fu_inc"]["value"]
                    if "fu_p" in adme:
                        p["fu_human"] = units.convert_fu(adme["fu_p"]["value"], adme["fu_p"]["unit"])
                    if "blood_plasma_ratio" in adme:
                        p["bp"] = adme["blood_plasma_ratio"]
                    if "permeability" in adme:
                        p["papp"] = adme["permeability"]["value"]
                    if "solubility" in adme:
                        p["sol"] = adme["solubility"]["value"]
                    if "clint_hep" in adme:
                        p["clint_hep"] = adme["clint_hep"]["value"]
                    if "fu_hep" in adme:
                        p["fu_hep"] = adme["fu_hep"]["value"]
                    if "logd" in adme:          # measured LogD overrides RDKit cLogP
                        p["logd"] = adme["logd"]
                    for eng in found:
                        wskey = ENGINE2WS.get(eng, eng)
                        if wskey in p:
                            src[wskey] = p[wskey]
                    for eng in missing:
                        miss.add(ENGINE2WS.get(eng, eng))
                    st.session_state.update(pf=p, src=src, missing=miss, fetched=True, source_name="CDD")
                    st.success(f"Filled from CDD: found {len(found)}, missing {len(missing)}")
                    st.rerun()
                except CDDError as exc:
                    st.error(str(exc))

    c_in, c_mid, c_sim = st.columns([1.1, 1.0, 1.2])

    with c_in:
        st.subheader("Inputs")
        compound_id = st.text_input("Compound ID", value=str(pf("id", "GEN-")))
        smiles = st.text_input("SMILES (optional)", value=str(pf("smiles", "")))  # smiles-ok
        mw = st.number_input("Molecular weight (g/mol)" + badge("mw"), value=float(pf("mw", 400.0)), min_value=1.0)
        logd = st.number_input("LogD" + badge("logd"), value=float(pf("logd", 3.0)))
        ion_class = st.selectbox("Ionisation class", ["neutral", "acidic", "basic"],
                                 index=["neutral", "acidic", "basic"].index(pf("class", "neutral")))
        st.markdown("**Targets** (free conc)")
        t1, t2, t3 = st.columns(3)
        css_max = t1.number_input("Css,max (nM)", value=0.0, min_value=0.0)
        auc = t2.number_input("AUC (nM·h)", value=0.0, min_value=0.0)
        css_trough = t3.number_input("Css,trough (nM)", value=50.0, min_value=0.0)

        # A field is "populated" if it came from a source (CDD) or its prefill is
        # non-blank. Populated fields render in the open; blank/default ones are
        # tucked into collapsed expanders to keep the worksheet compact.
        def _populated(field, blank=0.0):
            if field in st.session_state.get("src", {}):
                return True
            try:
                return abs(float(pf(field, blank)) - float(blank)) > 1e-9
            except (TypeError, ValueError):
                return bool(pf(field, blank))

        def _vfield(container, field, label, default, **kw):
            return container.number_input(label + badge(field),
                                          value=float(pf(field, default)), **kw)

        st.markdown("**In vivo PK**  (CL mL/min/kg · Vdss L/kg · F %)")
        if is_pre:
            st.caption("Pre-synthesis: animal in vivo PK usually unavailable; leave 0 and use "
                       "Øie–Tozer or Nucleus ML for Vd.")
        invivo = {}

        def _invivo_row(container, sp):
            a, b, d = container.columns(3)
            cl = a.number_input(f"{sp} CL" + badge(f"cl_{sp}"), value=float(pf(f"cl_{sp}", 0.0)), min_value=0.0)
            vd = b.number_input(f"{sp} Vdss" + badge(f"vd_{sp}"), value=float(pf(f"vd_{sp}", 0.0)), min_value=0.0)
            f = d.number_input(f"{sp} F%" + badge(f"F_{sp}"), value=float(pf(f"F_{sp}", 0.0)), min_value=0.0, max_value=100.0)
            invivo[sp] = {"cl": cl, "vd": vd, "F": f}

        active_sp = [sp for sp in ANIMALS
                     if any(_populated(f"{m}_{sp}") for m in ("cl", "vd", "F"))]
        blank_sp = [sp for sp in ANIMALS if sp not in active_sp]
        for sp in active_sp:
            _invivo_row(st, sp)
        if blank_sp:
            iv_exp = st.expander(f"➕ Add in vivo PK — {', '.join(blank_sp)} (blank)", expanded=False)
            for sp in blank_sp:
                _invivo_row(iv_exp, sp)

        st.markdown("**In vitro data**")
        _vitro_fields = [("clint_mic", 0.0), ("fu_mic", 0.0), ("clint_hep", 0.0),
                         ("fu_hep", 0.0), ("papp", 0.0), ("sol", 0.0), ("cl_direct", 0.0)]
        _vitro_fields += [(f"fu_{sp}", 0.01) for sp in ANIMALS]
        _any_blank = any(not _populated(f, b) for f, b in _vitro_fields)
        more = (st.expander("➕ Other in vitro fields (blank / default)", expanded=False)
                if _any_blank else st)

        def _vitro(field, label, default, **kw):
            return _vfield(st if _populated(field, default) else more, field, label, default, **kw)

        clint_mic = _vitro("clint_mic", "Human microsomal CLint (µL/min/mg)", 0.0, min_value=0.0)
        fu_mic = _vitro("fu_mic", "fu,mic (0 = predict)", 0.0, min_value=0.0, max_value=1.0)
        clint_hep = _vitro("clint_hep", "Human hepatocyte CLint (µL/min/10⁶)", 0.0, min_value=0.0)
        fu_hep = _vitro("fu_hep", "fu,hep (0 = predict)", 0.0, min_value=0.0, max_value=1.0)
        # Core assumptions — always visible
        fu_human = st.number_input("Human fu,p" + badge("fu_human"), value=float(pf("fu_human", 0.01)), min_value=0.0001, max_value=1.0, format="%.4f")
        bp = st.number_input("Human blood:plasma ratio" + badge("bp"), value=float(pf("bp", 1.0)), min_value=0.01)
        papp = _vitro("papp", "Caco-2/MDCK Papp (1e-6 cm/s)", 0.0, min_value=0.0)
        solubility = _vitro("sol", "Solubility (µM)", 0.0, min_value=0.0)
        cl_direct = _vitro("cl_direct", "Predicted human CL (mL/min/kg, direct)", 0.0, min_value=0.0,
                           help="ML-predicted human CL (e.g. Nucleus Microsomal/Hepatocyte "
                                "Stability) used directly, bypassing IVIVE.")
        # Animal fu,p — populated ones visible, blanks alongside their species in the expander
        for sp in ANIMALS:
            container = st if _populated(f"fu_{sp}", 0.01) else more
            invivo[sp]["fu"] = container.number_input(
                f"{sp} fu,p" + badge(f"fu_{sp}"), value=float(pf(f"fu_{sp}", 0.01)),
                min_value=0.0001, max_value=1.0, format="%.4f")

        with st.expander("Estimate fu,p / B:P from structure (rough)"):
            est_fup = props.predict_fu_p(logd)
            est_bp = props.predict_blood_plasma_ratio(ion_class)
            st.caption(f":orange[est] fu,p ≈ {est_fup:.3g} · B:P ≈ {est_bp:.2g}  "
                       "(placeholder QSAR — prefer measured / Nucleus ML)")
            if st.checkbox("Use estimates for blank (default) fields"):
                if source_of("fu_human", fu_human) == "default":
                    fu_human = est_fup
                if source_of("bp", bp) == "default":
                    bp = est_bp

    with c_mid:
        st.subheader("Selections")
        interval = st.selectbox("Dosing interval", ["QD", "BID"], index=1)
        tau_h = 24.0 if interval == "QD" else 12.0
        target_type = st.selectbox("Target", ["Cmin", "Cmax", "AUC"], index=0)
        target_val = {"Cmin": css_trough, "Cmax": css_max, "AUC": auc}[target_type]
        basis = st.selectbox("Predict human CL & Vd from",
                             ["In vitro (IVIVE)", "In vivo (allometry)", "Both"],
                             index=0 if is_pre else 2,
                             help="In vitro = IVIVE hepatic CL + Øie–Tozer Vd (no animal data needed). "
                                  "In vivo = animal single-species allometry for both CL and Vd.")
        iv_cl_method = st.radio("In vivo CL method", ["Single species", "Multi-species allometry"],
                                horizontal=True)
        scale_sp = st.selectbox("In vivo: species to scale from", ANIMALS, index=ANIMALS.index("cyno"))
        msa_fu_correct = st.checkbox("Multi-species: regress unbound CL (CL/fu)", value=False) \
            if iv_cl_method == "Multi-species allometry" else False
        cl_opts = ["Predicted human CL (direct)", "Hepatocytes", "Microsomes"]
        cl_route = st.selectbox("Human CL source (in vitro / ML)", cl_opts, index=0 if is_pre else 1)
        f_invitro = st.number_input("Assumed F% (in vitro dose)", value=50.0, min_value=1.0, max_value=100.0)
        covalent = st.checkbox("Covalent / irreversible program")
        if covalent:
            st.warning("Covalent inhibitors violate the reversible well-stirred CL and steady-state "
                       "assumptions. Treat the CL-based dose outputs as not applicable — use "
                       "kinact/KI- or target-turnover-driven methods instead.")
        est_F = st.checkbox("Estimate F mechanistically (Fa·Fg·Fh)")
        bcs = st.selectbox("BCS class (Fa limit)", [1, 2, 3, 4], index=0) if est_F else None

        st.markdown("**Vdss method**")
        st.caption("Vss cannot come from microsomes/hepatocytes (CL only). Use animal Vdss "
                   "free-fraction-scaled to human (standard), Øie–Tozer (needs tissue fu,t), or ML.")
        # Animal single-species is the default even for the in-vitro CL basis, because
        # in-vitro assays don't yield Vd; pre-synthesis (no animal data) defaults to Øie–Tozer.
        vd_method = st.selectbox("Predict Vdss by", ["Animal single-species", "Øie–Tozer", "Nucleus ML"],
                                 index=1 if is_pre else 0)
        if vd_method == "Animal single-species":
            vd_from = st.selectbox