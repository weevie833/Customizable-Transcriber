"""Regression tests for Index Compare's HTTP layer (app.py) -- exercises
the real Handler on an ephemeral port (see tests/conftest.py's live_server
fixture), the same way tests/test_run_concurrency.py already does, rather
than calling the handler methods directly, so a future change that moves
one of these calls outside _security_check() or breaks route dispatch
would actually be caught here."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

from xls_conversion.ai_parser import RECORD_TYPES
from xls_conversion.spreadsheet_export import rows_to_xlsx

import app as ctapp
import index_compare.scoring as scoring

MATRIMONI = RECORD_TYPES["matrimoni"]


def _matrimoni_xlsx(rows: list[dict[str, str]]) -> bytes:
    return rows_to_xlsx(
        MATRIMONI.group_headers,
        MATRIMONI.column_headers,
        MATRIMONI.fields,
        rows,
        MATRIMONI.sheet_name,
        numeric_columns=MATRIMONI.numeric_columns,
        padded_column=MATRIMONI.padded_column,
        column_widths=list(MATRIMONI.column_widths),
    )


def _row(**fields) -> dict[str, str]:
    row = {field: "" for field in MATRIMONI.fields}
    row.update(fields)
    return row


def _multipart_body(fields: dict[str, str], files: dict[str, tuple[str, bytes]]) -> tuple[bytes, str]:
    boundary = "----indexcomparetestboundary"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    for name, (filename, content) in files.items():
        parts.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8")
            + content
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _get(host, port, path, cookiejar):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar))
    req = urllib.request.Request(f"http://{host}:{port}{path}", headers={"Host": f"{host}:{port}"})
    return opener.open(req, timeout=5)


def _post_multipart(host, port, cookiejar, path, fields, files):
    body, content_type = _multipart_body(fields, files)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar))
    req = urllib.request.Request(
        f"http://{host}:{port}{path}",
        data=body,
        method="POST",
        headers={"Host": f"{host}:{port}", "Content-Type": content_type},
    )
    try:
        return opener.open(req, timeout=5)
    except urllib.error.HTTPError as exc:
        # respond_json()'s error path returns a real 4xx status -- still a
        # perfectly readable JSON body, just not a 2xx urlopen() will hand
        # back without raising.
        return exc


def _post_json(host, port, cookiejar, path, payload):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar))
    req = urllib.request.Request(
        f"http://{host}:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Host": f"{host}:{port}", "Content-Type": "application/json"},
    )
    try:
        return opener.open(req, timeout=5)
    except urllib.error.HTTPError as exc:
        return exc


def test_inspect_auto_detects_an_app_shaped_file(live_server):
    host, port = live_server
    jar = CookieJar()
    _get(host, port, "/", jar)

    xlsx_bytes = _matrimoni_xlsx([_row(page_number="34", groom_given_name="Giuseppe")])
    response = _post_multipart(
        host, port, jar, "/api/index-compare/inspect", {}, {"file": ("index.xlsx", xlsx_bytes)}
    )
    data = json.loads(response.read())
    assert data["auto_detected"] is True
    assert data["record_type"] == "matrimoni"


def test_inspect_reports_needs_mapping_for_a_custom_template(live_server):
    host, port = live_server
    jar = CookieJar()
    _get(host, port, "/", jar)

    custom_bytes = rows_to_xlsx(
        ["", "Groom"], ["Loc", "Name"], ["locator", "name"], [{"locator": "34", "name": "Giuseppe"}], "Custom"
    )
    response = _post_multipart(
        host, port, jar, "/api/index-compare/inspect", {}, {"file": ("custom.xlsx", custom_bytes)}
    )
    data = json.loads(response.read())
    assert data["auto_detected"] is False
    assert data["worksheets"][0]["name"] == "Custom"
    assert any(rt["value"] == "matrimoni" for rt in data["record_types"])


def test_analyze_end_to_end_accuracy_mode(live_server):
    host, port = live_server
    jar = CookieJar()
    _get(host, port, "/", jar)

    truth_bytes = _matrimoni_xlsx([_row(page_number="34", groom_given_name="Mauritzius", bride_last_name="Trunzo")])
    candidate_bytes = _matrimoni_xlsx(
        [_row(page_number="34", groom_given_name="Mauritius", bride_last_name="de Franco")]
    )
    response = _post_multipart(
        host,
        port,
        jar,
        "/api/index-compare/analyze",
        {"ground_truth_label": "ORIG", "candidate_label_0": "Gemini"},
        {"ground_truth_file": ("orig.xlsx", truth_bytes), "candidate_file_0": ("gemini.xlsx", candidate_bytes)},
    )
    data = json.loads(response.read())
    assert data["record_type"] == "matrimoni"
    assert data["ground_truth_label"] == "ORIG"
    result = data["result"]
    assert result["mode"] == "accuracy"
    assert result["candidates"][0]["label"] == "Gemini"
    assert result["candidates"][0]["category_counts"] == {"spelling_variant": 1, "differs": 1}


def test_analyze_end_to_end_agreement_mode_when_no_ground_truth(live_server):
    host, port = live_server
    jar = CookieJar()
    _get(host, port, "/", jar)

    candidate_a = _matrimoni_xlsx([_row(page_number="34", groom_given_name="Giuseppe")])
    candidate_b = _matrimoni_xlsx([_row(page_number="34", groom_given_name="Marco")])
    response = _post_multipart(
        host,
        port,
        jar,
        "/api/index-compare/analyze",
        {"candidate_label_0": "Gemini", "candidate_label_1": "Claude"},
        {"candidate_file_0": ("a.xlsx", candidate_a), "candidate_file_1": ("b.xlsx", candidate_b)},
    )
    data = json.loads(response.read())
    assert data["result"]["mode"] == "agreement"


def test_analyze_reports_needs_mapping_instead_of_a_generic_error(live_server):
    host, port = live_server
    jar = CookieJar()
    _get(host, port, "/", jar)

    custom_bytes = rows_to_xlsx(
        ["", "Groom"], ["Loc", "Name"], ["locator", "name"], [{"locator": "34", "name": "Giuseppe"}], "Custom"
    )
    candidate_bytes = _matrimoni_xlsx([_row(page_number="34", groom_given_name="Giuseppe")])
    response = _post_multipart(
        host,
        port,
        jar,
        "/api/index-compare/analyze",
        {"ground_truth_label": "ORIG", "candidate_label_0": "Gemini"},
        {"ground_truth_file": ("orig.xlsx", custom_bytes), "candidate_file_0": ("gemini.xlsx", candidate_bytes)},
    )
    data = json.loads(response.read())
    assert "needs_mapping" in data
    assert data["needs_mapping"][0]["slot"] == "ground_truth"


def test_analyze_with_an_explicit_mapping_for_a_custom_ground_truth(live_server):
    host, port = live_server
    jar = CookieJar()
    _get(host, port, "/", jar)

    custom_bytes = rows_to_xlsx(
        ["", "Groom"], ["Loc", "Name"], ["locator", "name"], [{"locator": "34", "name": "Giuseppe"}], "Custom"
    )
    mapping_response = _post_json(
        host,
        port,
        jar,
        "/api/index-compare/suggest-mapping",
        {"record_type": "matrimoni", "header_row1": ["", "Groom"], "header_row2": ["Loc", "Name"]},
    )
    mapping_data = json.loads(mapping_response.read())
    assert mapping_data["mapping"]["groom_given_name"] == 1

    candidate_bytes = _matrimoni_xlsx([_row(page_number="34", groom_given_name="Giuseppe")])
    ground_truth_mapping = json.dumps(
        {"record_type": "matrimoni", "sheet_name": "Custom", "mapping": mapping_data["mapping"]}
    )
    response = _post_multipart(
        host,
        port,
        jar,
        "/api/index-compare/analyze",
        {
            "ground_truth_label": "ORIG",
            "ground_truth_mapping": ground_truth_mapping,
            "candidate_label_0": "Gemini",
        },
        {"ground_truth_file": ("orig.xlsx", custom_bytes), "candidate_file_0": ("gemini.xlsx", candidate_bytes)},
    )
    data = json.loads(response.read())
    assert "needs_mapping" not in data
    assert data["result"]["candidates"][0]["category_counts"] == {}


def test_report_endpoint_streams_an_xlsx(live_server):
    host, port = live_server
    jar = CookieJar()
    _get(host, port, "/", jar)

    result = scoring.compare_indexes(
        MATRIMONI,
        ("ORIG", [_row(page_number="34", groom_given_name="Giuseppe")]),
        [("Gemini", [_row(page_number="34", groom_given_name="Marco")])],
    )
    response = _post_json(
        host, port, jar, "/api/index-compare/report", {"result": result, "ground_truth_label": "ORIG"}
    )
    assert response.status == 200
    assert response.headers.get("Content-Type") == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    body = response.read()
    assert body[:2] == b"PK"  # a real ZIP/XLSX container


def test_report_endpoint_requires_a_result(live_server):
    host, port = live_server
    jar = CookieJar()
    _get(host, port, "/", jar)
    response = _post_json(host, port, jar, "/api/index-compare/report", {})
    data = json.loads(response.read())
    assert "error" in data
