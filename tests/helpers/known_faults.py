"""Known device-side faults that hardware tests tolerate.

Kept in one place so a test never hard-codes an error string, and so the list of
things we are deliberately working around stays visible and reviewable rather
than scattered through `except` clauses.
"""

# The loader's medium init runs synchronously inside the USB completion handler.
# When it fails, the gadget stops serving *both* endpoints -- the host cannot
# even send the response-less reboot command -- so nothing on this side can
# recover it; only a power cycle can. Documented in
# docs/internal/notes.md ("MMC 初始化失败会把 loader 卡死").
MEDIUM_PROBE_FAILURE = "U-Boot 模式探测失败"


def is_known_medium_probe_failure(exc):
    """True if `exc` is the loader medium-init fault described above.

    Narrow on purpose: a hardware test should retry past this one documented
    defect and nothing else, or it stops being able to catch real regressions.
    """
    return MEDIUM_PROBE_FAILURE in str(exc)
