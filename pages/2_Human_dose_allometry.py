# smiles-ok-file
"""
Human dose worksheet - the full V5 workflow, as a page of the unified tool.

Single- and multi-species allometry, well-stirred IVIVE, Oie-Tozer Vdss, Nucleus ML,
pre-/post-synthesis modules, AUC/Cmin/Cmax dosing, profile plot and Excel export.
Runs the complete legacy human app (app.py) so nothing from V5 is lost.
"""
import os
import runpy

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
runpy.run_path(os.path.join(_ROOT, "app.py"), run_name="__main__")
