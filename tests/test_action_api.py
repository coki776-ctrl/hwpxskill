import base64
import json
import sys
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import action_ext
import app as app_module


def _write_hwpx(path: Path, paragraphs: int = 50, needle: str = "needle") -> None:
    ns = "http://www.hancom.co.kr/hwpml/2011/paragraph"
    body = "".join(
        f'<hp:p id="{index}" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0"><hp:t>{needle} paragraph {index}</hp:t></hp:run></hp:p>'
        for index in range(paragraphs)
    )
    xml = f'<hp:sec xmlns:hp="{ns}">{body}</hp:sec>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/hwp+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "Contents/content.hpf",
            '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/"><opf:manifest>'
            '<opf:item id="header" href="Contents/header.xml"/>'
            '<opf:item id="section0" href="Contents/section0.xml"/>'
            "</opf:manifest></opf:package>",
        )
        archive.writestr("Contents/header.xml", "<header/>")
        archive.writestr("Contents/section0.xml", xml)


def _mock_file_download(monkeypatch, tmp_path: Path, paragraphs: int = 50) -> None:
    def download(_ref, dst):
        _write_hwpx(dst, paragraphs)

    monkeypatch.setattr(action_ext, "download_action_hwpx", download)
    monkeypatch.setattr(action_ext, "validate_hwpx", lambda _path: [])


def _payload(**extra):
    value = {
        "openaiFileIdRefs": [{
            "name": "input.hwpx",
            "download_link": "https://files.oaiusercontent.com/test",
        }]
    }
    value.update(extra)
    return value


def test_inspect_summary_is_bounded_and_contains_no_slots(monkeypatch, tmp_path):
    _mock_file_download(monkeypatch, tmp_path, paragraphs=500)
    response = TestClient(action_ext.app).post("/action/inspect-summary", json=_payload())
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "source": "input.hwpx",
        "total_slots": 500,
        "paragraph_slots": 500,
        "cell_slots": 0,
    }
    assert len(response.content) < 200
    assert "slots" not in response.json()


def test_find_returns_at_most_ten_slots(monkeypatch, tmp_path):
    _mock_file_download(monkeypatch, tmp_path, paragraphs=50)
    response = TestClient(action_ext.app).post(
        "/action/find", json=_payload(search_text="needle", limit=10)
    )
    body = response.json()
    assert response.status_code == 200
    assert body["matched_slots"] == 50
    assert body["returned"] == 10
    assert body["truncated"] is True
    assert len(body["slots"]) == 10
    assert "table" not in body["slots"][0]


def test_action_edit_applies_eight_slot_edits_and_preserves_structure(monkeypatch, tmp_path):
    source = tmp_path / "source.hwpx"
    _write_hwpx(source, paragraphs=8, needle="2026?숇뀈??)
    monkeypatch.setattr(app_module, "download_action_hwpx", lambda _ref, dst: dst.write_bytes(source.read_bytes()))

    payload = _payload(slot_edits=[
        {"slot_key": f"p:{index}", "new_text": f"2027?숇뀈??paragraph {index}"}
        for index in range(8)
    ])
    response = TestClient(action_ext.app).post("/action/edit", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["validated"] is True

    output = tmp_path / "edited.hwpx"
    output.write_bytes(base64.b64decode(body["openaiFileResponse"][0]["content"]))
    assert app_module.validate_hwpx(str(output)) == []
    assert app_module.structure_errors(source, output) == []
    profile = app_module.collect_slots(output, include_empty_cells=False)
    assert len(profile["slots"]) == 8
    assert all("2027?숇뀈?? in slot["preview"] for slot in profile["slots"])
    assert all("2026?숇뀈?? not in slot["preview"] for slot in profile["slots"])


def test_deployed_app_routes_and_operation_ids_are_unique():
    routes = {
        (route.path, method): getattr(route, "operation_id", None)
        for route in action_ext.app.routes
        if hasattr(route, "methods")
        for method in route.methods
    }
    assert routes[("/inspect", "POST")] == "inspectHwpxMultipart"
    assert routes[("/validate", "POST")] == "validateHwpxMultipart"
    assert routes[("/edit", "POST")] == "editHwpxMultipart"
    assert routes[("/action/inspect-summary", "POST")] == "inspectHwpx"
    assert routes[("/action/edit", "POST")] == "editHwpx"
    operation_ids = [value for value in routes.values() if value]
    assert len(operation_ids) == len(set(operation_ids))


def test_committed_openapi_matches_action_request_and_response_shapes():
    import yaml

    spec = yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))
    summary = spec["paths"]["/action/inspect-summary"]["post"]
    assert summary["operationId"] == "inspectHwpx"
    response_props = spec["components"]["schemas"]["InspectSummaryResponse"]["properties"]
    assert set(response_props) == {
        "ok", "source", "total_slots", "paragraph_slots", "cell_slots"
    }
    ref_items = summary["requestBody"]["content"]["application/json"]["schema"]["properties"]["openaiFileIdRefs"]["items"]
    assert ref_items == {"$ref": "#/components/schemas/ActionFileRef"}
    assert spec["components"]["schemas"]["FindResponse"]["properties"]["slots"]["maxItems"] == 10
    edit = spec["paths"]["/action/edit"]["post"]
    assert edit["operationId"] == "editHwpx"
    edit_properties = edit["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert {"slot_edits", "text_replacements", "paragraph_edits"} <= set(edit_properties)
    assert not ({"slots", "replacements", "paragraphs"} & set(edit_properties))
    assert edit_properties["slot_edits"]["items"] == {"$ref": "#/components/schemas/SlotEdit"}
    for model in ("SlotEdit", "TextReplacement", "ParagraphEdit"):
        assert spec["components"]["schemas"][model]["additionalProperties"] is False
        runtime_schema = getattr(app_module, model).model_json_schema()
        assert runtime_schema["additionalProperties"] is False
        assert set(runtime_schema["properties"]) == set(
            spec["components"]["schemas"][model]["properties"]
        )

    action_route = next(
        route for route in action_ext.app.routes
        if getattr(route, "path", None) == "/action/edit"
    )
    assert action_route.operation_id == edit["operationId"]
    assert action_route.body_field.type_ is app_module.ActionEditRequest
    assert action_route.response_model is app_module.ActionEditResponse

