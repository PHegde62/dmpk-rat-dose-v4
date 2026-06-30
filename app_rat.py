# smiles-ok-file  (contains only public reference SMILES)
"""
DMPK Rat Dose Predictor - V4 worksheet UI.

A rat-targeted Streamlit worksheet over the V4 engine. Pick the in-vitro
clearance source (microsomes / hepatocytes / direct rat CL) and the Vss method,
auto-fill rat ADME from CDD or enter it by hand, then get the rat maintenance
dose, a plasma concentration-time profile, and the full IVIVE breakdown
(including predicted-vs-observed CL when an observed rat CL is available). A batch
tab runs the same over an uploaded SMILES table. Every run can be downloaded as
the V4 Excel workbook (predictions + PK profiles + IVIVE sheets).

Run:  streamlit run app_rat.py
"""
from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from dmpk_predictor import units
from dmpk_predictor.rat_dose import predict_rat_dose
from dmpk_predictor.rat_batch import run_rat_batch
from dmpk_predictor.rat_export import rat_batch_to_excel_bytes
from dmpk_predictor.cdd_client import fetch_adme_from_cdd, CDDError
from dmpk_predictor.cdd_config import CDDSettings

st.set_page_config(page_title="DMPK Rat Dose Predictor", page_icon="🐀", layout="wide")

CL_SOURCE_LABELS = {"Microsomes (RLM)": "microsome",
                    "Hepatocytes (RH)": "hepatocyte",
                    "Direct rat CL (mL/min/kg)": "direct",
                    "fu-calibrated (empirical)": "fu_empirical"}
VSS_LABELS = ["Measured rat Vss", "Øie–Tozer (rat)"]

# Tooltip + footnote text explaining each dropdown so the choice is unambiguous.
CL_SOURCE_HELP = (
    "How rat clearance (CL) — which drives the dose — is estimated:\n\n"
    "• **Microsomes (RLM)** — scale rat liver-microsome CLint through the well-stirred IVIVE model.\n"
    "• **Hepatocytes (RH)** — same well-stirred IVIVE from rat hepatocyte CLint (captures some non-CYP / uptake routes microsomes miss).\n"
    "• **Direct rat CL** — you type a measured/known rat CL (mL/min/kg); IVIVE is bypassed.\n"
    "• **fu-calibrated (empirical)** — predict CL from plasma fu via a series-calibrated fit, *not* from CLint. "
    "Use when in-vitro CLint does not rank your series well (validated on NIK: restored compound ranking). "
    "Re-fit the calibration per series and supply a reliable fu."
)
CL_SOURCE_FOOTNOTE = (
    "**CL source:** Microsomes / Hepatocytes = IVIVE from in-vitro CLint · "
    "Direct = your measured rat CL · "
    "fu-calibrated = CL predicted from fu (series-calibrated; best for *ranking* when CLint does not discriminate)."
)
VSS_HELP = ("Volume of distribution used for half-life and the profile. "
            "**Measured rat Vss** (from rat IV PK) is preferred; **Øie–Tozer (rat)** is a fu-based estimate used only when no measured Vss is given.")
TARGET_HELP = ("What free-drug exposure the dose must hit: **Cmin** = trough kept above target · "
               "**Cmax** = peak · **AUC** = total exposure over the interval. "
               "For short-half-life compounds prefer **AUC** (a trough target can blow the dose up).")


def pf(key, default):
    return st.session_state.get("pf", {}).get(key, default)


@st.cache_data(show_spinner=False, ttl=3600)
def _cached_cdd(ident, is_smiles, vault, token, agg):
    return fetch_adme_from_cdd(ident, is_smiles=is_smiles,
                               settings=CDDSettings(vault_id=vault, token=token, aggregation=agg))


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("CDD Vault (optional)")
    use_cdd_global = st.checkbox("Connect to CDD to auto-fill rat ADME", value=False,
                                 help="Off by default — the tool works fully without CDD. "
                                      "Turn on only if you want to pull rat ADME by GEN-ID/SMILES.")
    if use_cdd_global:
        cdd_vault = st.text_input("Vault ID", value=os.environ.get("CDD_VAULT_ID", ""))
        cdd_token = st.text_input("API token", type="password",
                                  value=os.environ.get("CDD_TOKEN", ""))
        cdd_agg = st.selectbox("Aggregation", ["mean", "geomean", "median", "latest"], index=0)
        st.caption("🔒 You type these here at runtime — they're held only in memory for this "
                   "session and are **never** written to the code, the repo, or the server. "
                   "Readouts are pulled for the **rat** species.")
    else:
        cdd_vault, cdd_token, cdd_agg = "", "", "mean"
        st.caption("CDD is **off** — enter ADME by hand (worksheet) or upload a CSV (batch). "
                   "No credentials needed.")
    st.divider()
    st.caption("Rat physiology: Qh 80 mL/min/kg · liver 40 g/kg · MPPGL 45 · HPGL 117 · BW 0.25 kg.")

st.title("🐀 DMPK Rat Dose Predictor — V4")
st.caption("Rat in → rat out: no cross-species allometry. Predictions, not measurements.")

tab_ws, tab_batch = st.tabs(["Worksheet (single compound)", "Batch upload"])

# --------------------------------------------------------------------------- #
# Worksheet tab
# --------------------------------------------------------------------------- #
with tab_ws:
    with st.expander("⚡ Auto-fill rat ADME from CDD (optional — GEN-ID or SMILES)", expanded=False):
        if not use_cdd_global:
            st.info("CDD is off. Tick **Connect to CDD** in the sidebar and enter your Vault "
                    "ID + token to auto-fill, or just type the ADME fields below.")
        ident = st.text_input("GEN-ID or SMILES", key="ws_ident")
        kind = st.radio("Identifier", ["GEN-ID", "SMILES"], horizontal=True, key="ws_kind")
        if st.button("Fetch from CDD"):
            if not (cdd_vault and cdd_token):
                st.warning("Enter your CDD Vault ID and API token in the sidebar first "
                           "(tick 'Connect to CDD'). Nothing is stored — they live only in this session.")
                st.stop()
            try:
                adme, prov = _cached_cdd(ident.strip(), kind == "SMILES",
                                         cdd_vault, cdd_token, cdd_agg)
                p = {"id": prov.get("molecule_name") or ident.strip(),
                     "smiles": (ident.strip() if kind == "SMILES" else prov.get("smiles") or "")}
                if "clint" in adme:
                    p["clint_mic"] = adme["clint"]["value"]
                if "clint_hep" in adme:
                    p["clint_hep"] = adme["clint_hep"]["value"]
                if "fu_p" in adme:
                    p["fu_p"] = units.convert_fu(adme["fu_p"]["value"], adme["fu_p"].get("unit", "fraction"))
                if "blood_plasma_ratio" in adme:
                    p["bp"] = adme["blood_plasma_ratio"]
                if "permeability" in adme:
                    p["papp"] = adme["permeability"]["value"]
                if "solubility" in adme:
                    p["sol"] = adme["solubility"]["value"]
                rat_iv = adme.get("invivo", {}).get("rat", {})
                if "vd" in rat_iv:
                    p["vd_rat"] = rat_iv["vd"]
                if "cl" in rat_iv:
                    p["cl_obs"] = rat_iv["cl"]
                if "F" in rat_iv:
                    p["F_rat"] = rat_iv["F"]
                st.session_state["pf"] = p
                st.success(f"Filled from CDD: found {len(prov.get('found', []))}, "
                           f"missing {len(prov.get('missing', []))}")
                st.rerun()
            except CDDError as exc:
                st.error(str(exc))

    c_in, c_sel = st.columns([1.15, 1.0])

    with c_in:
        st.subheader("Compound & rat ADME")
        compound_id = st.text_input("Compound ID", value=str(pf("id", "GEN-")))
        smiles = st.text_input("SMILES", value=str(pf("smiles", "")))  # smiles-ok
        logd_in = st.text_input("LogD (blank = RDKit cLogP)", value=str(pf("logd", "")))
        ion = st.selectbox("Ionisation class", ["(auto)", "neutral", "acidic", "basic"], index=0)

        st.markdown("**In vitro (rat)**")
        clint_mic = st.number_input("Rat microsomal CLint (µL/min/mg)",
                                    value=float(pf("clint_mic", 0.0)), min_value=0.0)
        clint_hep = st.number_input("Rat hepatocyte CLint (µL/min/10⁶ cells)",
                                    value=float(pf("clint_hep", 0.0)), min_value=0.0)
        cl_direct = st.number_input("Direct rat CL (mL/min/kg)",
                                    value=float(pf("cl_direct", 0.0)), min_value=0.0)
        fu_p = st.number_input("Rat fu,p", value=float(pf("fu_p", 0.05)),
                               min_value=0.0001, max_value=1.0, format="%.4f")
        bp = st.number_input("Rat blood:plasma", value=float(pf("bp", 1.0)), min_value=0.01)
        papp = st.number_input("Caco-2/MDCK Papp (1e-6 cm/s)", value=float(pf("papp", 0.0)), min_value=0.0)
        sol = st.number_input("Solubility (µM)", value=float(pf("sol", 0.0)), min_value=0.0)
        vd_rat = st.number_input("Measured rat Vss (L/kg, 0 = none)",
                                 value=float(pf("vd_rat", 0.0)), min_value=0.0)
        cl_obs = st.number_input("Observed rat CL (mL/min/kg, 0 = none) — for IVIVE correlation",
                                 value=float(pf("cl_obs", 0.0)), min_value=0.0)

    with c_sel:
        st.subheader("Method & target")
        cl_source_label = st.selectbox("In vitro CL source", list(CL_SOURCE_LABELS.keys()),
                                       index=0, help=CL_SOURCE_HELP)
        cl_source = CL_SOURCE_LABELS[cl_source_label]
        st.caption(CL_SOURCE_FOOTNOTE)
        vss_method = st.selectbox("Vss method", VSS_LABELS, index=0, help=VSS_HELP)
        target_type = st.selectbox("Target", ["Cmin", "Cmax", "AUC"], index=0, help=TARGET_HELP)
        target_free = st.number_input("Free target (nM) — or free AUC (nM·h)", value=50.0, min_value=0.0)
        interval = st.selectbox("Dosing interval", ["QD (24 h)", "BID (12 h)", "custom"], index=1)
        tau = {"QD (24 h)": 24.0, "BID (12 h)": 12.0}.get(interval)
        if tau is None:
            tau = st.number_input("Custom τ (h)", value=12.0, min_value=0.5)
        ka = st.number_input("Absorption ka (1/h)", value=1.0, min_value=0.01)
        go = st.button("Predict rat dose", type="primary")

    if go:
        adme = {"fu_p": {"value": fu_p, "unit": "fraction"}, "blood_plasma_ratio": bp}
        if clint_mic > 0:
            adme["clint"] = {"value": clint_mic, "unit": "uL/min/mg", "matrix": "microsome"}
        if clint_hep > 0:
            adme["clint_hep"] = {"value": clint_hep, "unit": "uL/min/1e6 cells", "matrix": "hepatocyte"}
        if cl_direct > 0:
            adme["cl_direct"] = cl_direct
        if papp > 0:
            adme["permeability"] = {"value": papp, "unit": "1e-6 cm/s"}
        if sol > 0:
            adme["solubility"] = {"value": sol, "unit": "uM"}
        if vss_method == "Measured rat Vss" and vd_rat > 0:
            adme["vd_human"] = vd_rat   # engine slot for measured target-species Vss
        if F := pf("F_rat", 0):
            try:
                adme["bioavailability_pct"] = float(F)
            except (TypeError, ValueError):
                pass

        res = predict_rat_dose(
            smiles, adme, target_type=target_type, target_free=target_free,
            tau_hours=tau, ka_per_h=ka, cl_source=cl_source,
            cl_obs=(cl_obs or None),
            logd=(float(logd_in) if logd_in.strip() else None),
            ionisation_class=(None if ion == "(auto)" else ion))

        if res.get("error"):
            st.error(res["error"])
        else:
            if res.get("flag"):
                st.warning("⚠ " + res["flag"])
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Rat dose", f"{res['dose_mg']:.4g} mg")
            m2.metric("Rat dose", f"{res['dose_mg_kg']:.4g} mg/kg")
            m3.metric("Rat CL (pred)", f"{res['cl_rat_plasma_mL_min_kg']:.3g}", "mL/min/kg")
            m4.metric("F", f"{res['F_pct']:.0f}%")
            n1, n2, n3, n4 = st.columns(4)
            n1.metric("Rat Vss", f"{res['vss_rat_L_kg']:.3g} L/kg", res["vd_method"])
            n2.metric("t½", f"{res['t_half_h']:.2g} h" if res.get("t_half_h") else "—")
            n3.metric("E_H", f"{res['E_H']:.3f}")
            n4.metric("Target", f"{target_type} {target_free:g} nM")

            with st.expander("🔬 View IVIVE breakdown & correlation", expanded=True):
                rows = [
                    ("CL source", res.get("cl_source")),
                    ("Matrix", res.get("matrix")),
                    ("fu,inc (incubation)", res.get("fu_inc")),
                    ("CLint,liver scaled (mL/min/kg)", res.get("clint_liver_mL_min_kg")),
                    ("CLu,int (mL/min/kg)", res.get("cl_u_int_mL_min_kg")),
                    ("CLh,blood (mL/min/kg)", res.get("clh_blood_mL_min_kg")),
                    ("CLh,plasma = rat CL pred (mL/min/kg)", res.get("cl_rat_plasma_mL_min_kg")),
                    ("E_H (hepatic extraction)", res.get("E_H")),
                ]
                if res.get("cl_rat_obs_mL_min_kg"):
                    rows += [
                        ("Observed rat CL (mL/min/kg)", res.get("cl_rat_obs_mL_min_kg")),
                        ("CL IVIVE pred/obs", res.get("ivive_pred_over_obs")),
                        ("CL IVIVE fold-error", res.get("ivive_fold_error")),
                    ]
                rows += [
                    ("Vss Øie–Tozer pred (L/kg)", res.get("vss_pred_oie_L_kg")),
                    ("Vss used for dose (L/kg)", res.get("vss_rat_L_kg")),
                ]
                if res.get("vss_obs_L_kg"):
                    rows += [
                        ("Vss observed (L/kg)", res.get("vss_obs_L_kg")),
                        ("Vss pred/obs", res.get("vss_pred_over_obs")),
                        ("Vss fold-error", res.get("vss_fold_error")),
                    ]
                ivdf = pd.DataFrame(rows, columns=["IVIVE step", "Value"])
                st.dataframe(ivdf, hide_index=True, use_container_width=True)
                if res.get("ivive_fold_error"):
                    fe = res["ivive_fold_error"]
                    (st.success if fe <= 2 else st.warning)(
                        f"Predicted rat CL is within **{fe:.2f}-fold** of observed "
                        f"({'good' if fe <= 2 else 'check IVIVE for this chemotype'}).")
                if res.get("vss_fold_error"):
                    ve = res["vss_fold_error"]
                    (st.success if ve <= 2 else st.warning)(
                        f"Øie–Tozer Vss is within **{ve:.2f}-fold** of observed rat Vss.")

            if res.get("_profile_t_h"):
                prof = pd.DataFrame({"Time (h)": res["_profile_t_h"],
                                     "Free Cp (nM)": res["_profile_free_nM"]})
                if target_free > 0 and target_type != "AUC":
                    prof["Target (nM)"] = target_free
                st.line_chart(prof, x="Time (h)")

            # downloadable Excel (single compound)
            row = {k: v for k, v in res.items() if not k.startswith("_")}
            row["id"] = compound_id
            df1 = pd.DataFrame([row])
            profiles = ([{"id": compound_id, "smiles": smiles,
                          "t_h": res["_profile_t_h"], "free_nM": res["_profile_free_nM"]}]
                        if res.get("_profile_t_h") else [])
            xls = rat_batch_to_excel_bytes(df1, profiles, meta={
                "Compound": compound_id, "CL source": cl_source, "Vss method": vss_method,
                "Target": f"{target_type} {target_free:g} nM", "τ (h)": tau, "ka (1/h)": ka})
            st.download_button("⬇ Download Excel (predictions + profile + IVIVE)",
                               data=xls, file_name=f"rat_dose_{compound_id}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# --------------------------------------------------------------------------- #
# Batch tab
# --------------------------------------------------------------------------- #
with tab_batch:
    st.subheader("Batch: many SMILES → rat dose + profiles → Excel")
    st.caption("Upload a CSV with a `smiles` column (and optionally `id` = GEN-ID). "
               "Rat ADME is pulled from CDD when credentials are set; any ADME columns "
               "present in the file override / fill gaps. Template: examples/rat_batch_template.csv")
    up = st.file_uploader("Compounds CSV", type=["csv"], key="batch_up")
    b1, b2, b3, b4 = st.columns(4)
    b_src = b1.selectbox("CL source", list(CL_SOURCE_LABELS.keys()), index=0, key="b_src",
                         help=CL_SOURCE_HELP)
    b_tt = b2.selectbox("Target", ["Cmin", "Cmax", "AUC"], index=0, key="b_tt", help=TARGET_HELP)
    b_free = b3.number_input("Free target (nM)", value=50.0, min_value=0.0, key="b_free")
    b_tau = b4.number_input("τ (h)", value=12.0, min_value=0.5, key="b_tau")
    st.caption(CL_SOURCE_FOOTNOTE)
    use_cdd = st.checkbox("Pull ADME from CDD (needs credentials in sidebar)",
                          value=bool(cdd_vault and cdd_token))
    if up is not None and st.button("Run batch", type="primary"):
        raw = pd.read_csv(up)
        settings = CDDSettings(vault_id=cdd_vault, token=cdd_token, aggregation=cdd_agg) \
            if use_cdd else None
        with st.spinner(f"Running {len(raw)} compounds…"):
            df, profiles = run_rat_batch(
                raw, target_type=b_tt, target_free_nM=b_free, tau_hours=b_tau,
                cl_source=CL_SOURCE_LABELS[b_src], use_cdd=use_cdd, settings=settings)
        ok = int(df["error"].isna().sum()) if "error" in df else len(df)
        st.success(f"{len(df)} compounds · {ok} succeeded · {len(profiles)} profiles")
        show = [c for c in ["id", "mw", "cl_source", "cl_rat_plasma_mL_min_kg",
                            "cl_rat_obs_mL_min_kg", "ivive_fold_error", "F_pct",
                            "vss_rat_L_kg", "dose_mg", "dose_mg_kg", "flag", "error"]
                if c in df.columns]
        st.dataframe(df[show], hide_index=True, use_container_width=True)
        xls = rat_batch_to_excel_bytes(df, profiles, meta={
            "CL source": CL_SOURCE_LABELS[b_src], "Target": f"{b_tt} {b_free:g} nM",
            "τ (h)": b_tau, "ADME source": "CDD" if use_cdd else "input table"})
        st.download_button("⬇ Download Excel (predictions + profiles + IVIVE)",
                           data=xls, file_name="rat_dose_predictions.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
