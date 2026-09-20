"""Legacy compatibility shim for the old ManualOverrider import path.

Active Step 4 runtime code should prefer `manual_override_primitives` via
`Step4DraftController`. The stateful adapter remains available only through
this re-export for older tests and diagnostic scripts.
"""

from modules.scheduler.logic.manual_override_legacy import ManualOverrider


__all__ = ["ManualOverrider"]
