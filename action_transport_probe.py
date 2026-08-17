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
)
def create_rich_transport_stub(
    payload: app_module.CreateRichHwpxRequest,
) -> dict[str, bool | int]:
    """Temporary transport diagnostic with no auth or document work.

    Deliberately performs no API-key validation, Kordoc, HWPX, chart,
    file, or subprocess work. It only parses the JSON body and returns
    the response shape already declared in the committed OpenAPI schema.
    """
    return {
        "ok": True,
        "validated": False,
        "layout_warning_count": 0,
    }
