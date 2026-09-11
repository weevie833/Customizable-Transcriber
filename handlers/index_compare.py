"""HTTP handlers for the Index Compare feature (Test Mode's "Compare Indexes
(XLSX)" section, `/api/index-compare/*`). Business logic lives entirely in
the index_compare/ package (reader.py's column-mapping resolution,
scoring.py's compare_indexes(), report_docx.py's DOCX report builder) --
this module is only the HTTP-request-parsing/response-shaping layer on top
of it.
"""

from __future__ import annotations

import json

from xls_conversion.ai_parser import RECORD_TYPES
from index_compare.reader import NeedsMapping, resolve_index_file, suggest_mapping
from index_compare.report_docx import build_index_compare_report
from index_compare.scoring import compare_indexes
from http_utils import parse_json_body, parse_multipart_form


class IndexCompareHandlerMixin:
    def _index_compare_file_bytes(
        self, files: dict[str, tuple[str, bytes]], field_name: str, *, required: bool = True
    ) -> bytes:
        """Pull one named .xlsx file out of a parse_multipart_form() files
        dict -- the Index Compare analog of uploaded_docx_field()."""
        entry = files.get(field_name)
        if not entry or not entry[1]:
            if required:
                raise RuntimeError(f"Upload a file for {field_name.replace('_', ' ')}.")
            return b""
        filename, payload = entry
        if not filename.lower().endswith(".xlsx"):
            raise RuntimeError(f"{field_name.replace('_', ' ').title()} must be an .xlsx file.")
        return payload

    def _resolve_index_file_or_record_mapping_need(
        self, file_bytes: bytes, mapping_json: str, slot: str, needs_mapping: list[dict]
    ) -> tuple | None:
        """Wraps index_compare.reader.resolve_index_file(): on success
        returns its (config, rows, sheet_name); on NeedsMapping, appends a
        {slot, worksheets} entry to `needs_mapping` and returns None instead
        of raising, so the caller can keep resolving the *other* uploaded
        files and report every file that needs attention in one response
        rather than making the user fix them one at a time."""
        try:
            mapping = json.loads(mapping_json) if mapping_json else None
            return resolve_index_file(file_bytes, mapping)
        except NeedsMapping as exc:
            needs_mapping.append(
                {
                    "slot": slot,
                    "worksheets": [
                        {"name": ws.name, "header_row1": ws.header_row1, "header_row2": ws.header_row2}
                        for ws in exc.worksheets
                    ],
                }
            )
            return None

    def inspect_index_file(self) -> None:
        """Single-file precheck, called client-side right after each file
        input is chosen (before Run Comparison) -- lets the frontend show a
        column-mapping step immediately for a file that needs one, instead
        of the user discovering it only after filling in every other field
        and clicking Run."""
        try:
            files, _fields = parse_multipart_form(self)
            file_bytes = self._index_compare_file_bytes(files, "file")
            try:
                config, rows, sheet_name = resolve_index_file(file_bytes)
                self.respond_json(
                    {
                        "auto_detected": True,
                        "record_type": config.key,
                        "sheet_name": sheet_name,
                        "row_count": len(rows),
                    }
                )
            except NeedsMapping as exc:
                self.respond_json(
                    {
                        "auto_detected": False,
                        "worksheets": [
                            {"name": ws.name, "header_row1": ws.header_row1, "header_row2": ws.header_row2}
                            for ws in exc.worksheets
                        ],
                        "record_types": [{"value": key, "label": cfg.label} for key, cfg in RECORD_TYPES.items()],
                    }
                )
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def suggest_index_mapping(self) -> None:
        """Once the frontend knows a file needs mapping and the user has
        picked which of the 6 record types it is, this returns a best-guess
        column mapping (index_compare.reader.suggest_mapping()) to pre-fill
        the mapping UI, rather than making the user start from a blank
        dropdown for every field."""
        try:
            payload = parse_json_body(self)
            record_type = str(payload.get("record_type", ""))
            config = RECORD_TYPES.get(record_type)
            if not config:
                raise RuntimeError("Select a valid record type.")
            header_row1 = payload.get("header_row1")
            header_row2 = payload.get("header_row2")
            if not isinstance(header_row1, list) or not isinstance(header_row2, list):
                raise RuntimeError("Missing this worksheet's header rows.")
            mapping = suggest_mapping(record_type, [str(v) for v in header_row1], [str(v) for v in header_row2])
            self.respond_json(
                {
                    "fields": config.fields,
                    "field_group_labels": list(config.group_headers),
                    "field_column_labels": list(config.column_headers),
                    "mapping": mapping,
                }
            )
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def analyze_index_compare(self) -> None:
        try:
            files, fields = parse_multipart_form(self)
            needs_mapping: list[dict] = []

            config = None
            ground_truth = None
            gt_entry = files.get("ground_truth_file")
            if not gt_entry or not gt_entry[1]:
                raise RuntimeError("Upload a 100% Corrected index (ground truth) file to compare against.")
            gt_bytes = self._index_compare_file_bytes(files, "ground_truth_file")
            resolved = self._resolve_index_file_or_record_mapping_need(
                gt_bytes, fields.get("ground_truth_mapping", ""), "ground_truth", needs_mapping
            )
            if resolved:
                gt_config, gt_rows, _sheet = resolved
                gt_label = fields.get("ground_truth_label", "").strip() or "Ground truth"
                ground_truth = (gt_label, gt_rows)
                config = gt_config

            candidate_indexes = sorted(
                (name.removeprefix("candidate_file_") for name in files if name.startswith("candidate_file_")),
                key=lambda value: int(value) if value.isdigit() else value,
            )
            candidates: list[tuple[str, list[dict[str, str]]]] = []
            for index in candidate_indexes:
                file_bytes = self._index_compare_file_bytes(files, f"candidate_file_{index}")
                resolved = self._resolve_index_file_or_record_mapping_need(
                    file_bytes, fields.get(f"candidate_mapping_{index}", ""), f"candidate_{index}", needs_mapping
                )
                if resolved is None:
                    continue
                candidate_config, rows, _sheet = resolved
                if config is None:
                    config = candidate_config
                elif candidate_config.key != config.key:
                    raise RuntimeError(
                        f"All files must be the same record type -- expected {config.label}, but "
                        f"candidate {index} looks like {candidate_config.label}."
                    )
                label = fields.get(f"candidate_label_{index}", "").strip() or f"Candidate {index}"
                candidates.append((label, rows))

            if needs_mapping:
                self.respond_json(
                    {
                        "needs_mapping": needs_mapping,
                        "record_types": [{"value": key, "label": cfg.label} for key, cfg in RECORD_TYPES.items()],
                    }
                )
                return

            if not candidates:
                raise RuntimeError("Upload at least one candidate index to compare.")
            if config is None:
                raise RuntimeError("Could not determine a record type from the uploaded files.")

            result = compare_indexes(config, ground_truth, candidates)
            self.respond_json(
                {
                    "result": result,
                    "record_type": config.key,
                    "ground_truth_label": ground_truth[0] if ground_truth else "",
                }
            )
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def index_compare_report(self) -> None:
        try:
            payload = parse_json_body(self)
            result = payload.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("Run a comparison before downloading a report.")
            ground_truth_label = str(payload.get("ground_truth_label") or "")
            # Optional: lets the report render real column labels ("Father's
            # Given Name") instead of internal field names -- absent this,
            # build_index_compare_report() just falls back to the raw names.
            config = RECORD_TYPES.get(str(payload.get("record_type") or ""))
            data = build_index_compare_report(result, ground_truth_label, config)
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            self.send_header("Content-Disposition", 'attachment; filename="index-comparison-report.docx"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)
