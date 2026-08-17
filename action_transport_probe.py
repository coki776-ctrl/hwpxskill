from fastapi import Depends

import app as app_module
from rich_action_kordoc import app


def _remove_create_rich_route() -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == "/action/create-rich"
            and "POST" in getattr(route, "methods", set())
        )
    ]


_remove_create_rich_route()


@app.post(
    "/action/create-rich",
    operation_id="createRichHwpx",
    dependencies=[Depends(app_module.require_api_key)],
)
def create_rich_transport_stub(
    payload: app_module.CreateRichHwpxRequest,
) -> dict[str, bool | int]:
    """Temporary diagnostic stub matching the committed OpenAPI response shape.

    Deliberately performs no Kordoc, HWPX, chart, file, or subprocess work.
    """
    return {
        "ok": True,
        "validated": False,
        "layout_warning_count": 0,
    }


@app.post(
    "/action/transport-probe",
    operation_id="probeActionTransport",
    dependencies=[Depends(app_module.require_api_key)],
)
def probe_action_transport() -> dict[str, bool]:
    """Minimal authenticated endpoint for isolating GPT Action transport issues."""
    return {"ok": True}
