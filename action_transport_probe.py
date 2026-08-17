import time

from fastapi.responses import JSONResponse

from rich_action_kordoc import app


LAST_PROBE = {"hit_count": 0, "last_hit_unix": None}


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
    """Absolute-minimum transport diagnostic with an in-memory hit marker."""
    LAST_PROBE["hit_count"] += 1
    LAST_PROBE["last_hit_unix"] = time.time()
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "validated": False,
            "layout_warning_count": 0,
        },
    )


@app.get("/action/last-probe", include_in_schema=False)
def last_probe() -> dict:
    """Browser-readable diagnostic showing whether create-rich reached FastAPI."""
    return LAST_PROBE.copy()
