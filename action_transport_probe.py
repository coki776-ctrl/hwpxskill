from fastapi import Depends

import app as app_module
from rich_action_kordoc import app


@app.post(
    "/action/transport-probe",
    operation_id="probeActionTransport",
    dependencies=[Depends(app_module.require_api_key)],
)
def probe_action_transport() -> dict[str, bool]:
    """Minimal authenticated endpoint for isolating GPT Action transport issues.

    Deliberately performs no Kordoc, HWPX, filesystem, chart, or subprocess work.
    """
    return {"ok": True}
