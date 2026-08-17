from fastapi.responses import JSONResponse

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
def create_rich_transport_stub() -> JSONResponse:
    """Absolute-minimum transport diagnostic.

    Intentionally performs no auth, request-body parsing, Pydantic validation,
    Kordoc, HWPX, chart, file, subprocess, or response-model validation.
    FastAPI ignores any request body and returns a fixed HTTP 200 JSON payload.
    """
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "validated": False,
            "layout_warning_count": 0,
        },
    )
