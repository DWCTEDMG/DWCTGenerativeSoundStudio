"""Local override for SciPy special hooks used by the Studio backend build.

PyInstaller's upstream hook assumes that every SciPy >= 1.13 wheel ships the
`scipy.special._cdflib` extension. The Windows wheel in this backend venv does
not include that module, so we only collect the extensions that are actually
present for this build.
"""

from PyInstaller.utils.hooks import is_module_satisfies


hiddenimports = ["scipy.special._ufuncs_cxx"]

if is_module_satisfies("scipy >= 1.14.0"):
    hiddenimports += ["scipy.special._special_ufuncs"]
