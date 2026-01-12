"""
Combined report generator for inline / defect / fdc agents.
Reads each agent output/data and writes combined_report.md + combined_report.json.
"""

from __future__ import annotations
import os
import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

os.environ.setdefault(
    "OPENAI_API_KEY",
    "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",
)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_cmd(cmd: list[str], cwd: Path) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{proc.stderr}")
    return proc.stdout.strip()


def _parse_llm_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def _llm_overall_judge(payload: dict[str, Any], model: str) -> dict[str, str]:
    system_prompt = (
        "너는 반도체 품질 종합 판단 에이전트다. "
        "inline/defect/fdc 결과를 근거로 최종 PASS/FAIL을 판단한다. "
        "각 에이전트의 결과를 우선 신뢰하되, 근거가 충분한지 검토한다. "
        "반드시 JSON만 출력하라."
    )
    user_prompt = (
        "아래 입력을 바탕으로 종합 PASS/FAIL을 판단하라.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "출력 형식:\n"
        '{\"status\": \"PASS|FAIL\", \"reason\": \"한국어로 판단 근거\"}'
    )
    llm = ChatOpenAI(model=model, temperature=1)
    response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
    result = _parse_llm_json(response.content or "")
    status = str(result.get("status", "")).upper()
    if status not in {"PASS", "FAIL"}:
        raise ValueError(f"LLM output missing status PASS/FAIL: {result}")
    reason = str(result.get("reason", "")).strip()
    if not reason:
        raise ValueError("LLM output missing reason.")
    return {"status": status, "reason": reason}


def _resolve_image_csv(src: Path, images_base: Path, out_path: Path) -> Path:
    import csv

    with src.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV missing header row: {src}")
        if "image_file" not in reader.fieldnames:
            raise ValueError(f"CSV missing image_file column: {src}")
        rows = []
        for row in reader:
            image_file = (row.get("image_file") or "").strip()
            if image_file:
                image_path = Path(image_file)
                if not image_path.is_absolute():
                    image_path = images_base / image_path
                row["image_file"] = str(image_path)
            rows.append(row)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def _resolve_path(value: str | None, base_dir: Path) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _load_manifest(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    base_dir = path.parent

    inline_raw = data.get("inline", {}) if isinstance(data.get("inline", {}), dict) else {}
    defect_raw = data.get("defect", {}) if isinstance(data.get("defect", {}), dict) else {}
    fdc_raw = data.get("fdc", {}) if isinstance(data.get("fdc", {}), dict) else {}

    inline = {
        "csv": _resolve_path(inline_raw.get("csv"), base_dir),
        "spec": _resolve_path(inline_raw.get("spec"), base_dir),
        "notes": _resolve_path(inline_raw.get("notes"), base_dir),
        "alignment_tolerance": inline_raw.get("alignment_tolerance"),
        "model": inline_raw.get("model"),
    }
    defect = {
        "data_csv": _resolve_path(defect_raw.get("data_csv"), base_dir),
        "notes": _resolve_path(defect_raw.get("notes"), base_dir),
        "images_base": _resolve_path(defect_raw.get("images_base"), base_dir),
        "spec_total": defect_raw.get("spec_total"),
        "spec_dr": defect_raw.get("spec_dr"),
        "composite_horizontal": _resolve_path(defect_raw.get("composite_horizontal"), base_dir),
        "composite_vertical": _resolve_path(defect_raw.get("composite_vertical"), base_dir),
        "model": defect_raw.get("model"),
    }
    fdc = {
        "timeseries_csv": _resolve_path(fdc_raw.get("timeseries_csv"), base_dir),
        "trend_images_csv": _resolve_path(fdc_raw.get("trend_images_csv"), base_dir),
        "fail_csv": _resolve_path(fdc_raw.get("fail_csv"), base_dir),
        "notes": _resolve_path(fdc_raw.get("notes"), base_dir),
        "images_base": _resolve_path(fdc_raw.get("images_base"), base_dir),
        "composite_horizontal": _resolve_path(fdc_raw.get("composite_horizontal"), base_dir),
        "composite_vertical": _resolve_path(fdc_raw.get("composite_vertical"), base_dir),
        "model": fdc_raw.get("model"),
    }

    return {"inline": inline, "defect": defect, "fdc": fdc}


def _parse_report_status(report_path: Path) -> dict[str, str] | None:
    if not report_path.exists():
        return None
    lines = report_path.read_text(encoding="utf-8").splitlines()
    start_idx = None
    for idx, line in enumerate(lines):
        if line.strip() == "## Final Decision":
            start_idx = idx
            break
    if start_idx is None:
        return None

    status = ""
    reason = ""
    for line in lines[start_idx + 1 :]:
        if line.strip().startswith("## "):
            break
        if line.strip().startswith("- Status:"):
            status = line.split(":", 1)[1].strip()
        elif line.strip().startswith("- Reason:"):
            reason = line.split(":", 1)[1].strip()

    if not status:
        return None
    return {"status": status, "reason": reason}


def _resolve_dir(path_value: str, base_root: Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = base_root / path
    return path.resolve()


def _run_inline_agent(
    inline_dir: Path,
    inline_input: dict[str, Any] | None,
    default_model: str,
) -> None:
    inline_csv = inline_input.get("csv") if inline_input else None
    inline_spec = inline_input.get("spec") if inline_input else None
    inline_notes = inline_input.get("notes") if inline_input else None
    inline_tolerance = inline_input.get("alignment_tolerance") if inline_input else None
    inline_model = inline_input.get("model") if inline_input else None

    cmd = ["python", "agent.py", "--model", inline_model or default_model]
    if inline_csv:
        cmd.extend(["--csv", str(inline_csv)])
    if inline_spec:
        cmd.extend(["--spec", str(inline_spec)])
    if inline_notes:
        cmd.extend(["--notes", str(inline_notes)])
    if inline_tolerance is not None:
        cmd.extend(["--alignment-tolerance", str(inline_tolerance)])
    _run_cmd(cmd, cwd=inline_dir)


def _run_defect_agent(
    defect_dir: Path,
    defect_input: dict[str, Any] | None,
    scratch_dir: Path,
) -> None:
    data_csv = defect_input.get("data_csv") if defect_input else None
    if not data_csv:
        data_csv = defect_dir / "defect_data.csv"
    images_base = defect_input.get("images_base") if defect_input else None
    if not images_base:
        images_base = data_csv.parent

    resolved_csv = _resolve_image_csv(
        data_csv,
        images_base,
        scratch_dir / "defect_data_resolved.csv",
    )

    cmd = ["python", "agent.py", "--data-csv", str(resolved_csv)]
    notes = defect_input.get("notes") if defect_input else None
    if notes:
        cmd.extend(["--engineer-notes-file", str(notes)])
    model = defect_input.get("model") if defect_input else None
    if model:
        cmd.extend(["--model", str(model)])
    _run_cmd(cmd, cwd=defect_dir)


def _run_fdc_agent(
    fdc_dir: Path,
    fdc_input: dict[str, Any] | None,
    scratch_dir: Path,
) -> None:
    timeseries_csv = fdc_input.get("timeseries_csv") if fdc_input else None
    if not timeseries_csv:
        timeseries_csv = fdc_dir / "timeseries.csv"
    trend_images_csv = fdc_input.get("trend_images_csv") if fdc_input else None
    if not trend_images_csv:
        trend_images_csv = fdc_dir / "trend_images.csv"
    fail_csv = fdc_input.get("fail_csv") if fdc_input else None
    if not fail_csv:
        fail_csv = fdc_dir / "taq_fail.csv"
    images_base = fdc_input.get("images_base") if fdc_input else None
    if not images_base:
        images_base = trend_images_csv.parent

    resolved_images_csv = _resolve_image_csv(
        trend_images_csv,
        images_base,
        scratch_dir / "trend_images_resolved.csv",
    )

    cmd = [
        "python",
        "agent.py",
        "--timeseries",
        str(timeseries_csv),
        "--images",
        str(resolved_images_csv),
        "--fail",
        str(fail_csv),
    ]
    notes = fdc_input.get("notes") if fdc_input else None
    if notes:
        cmd.extend(["--engineer-notes-file", str(notes)])
    model = fdc_input.get("model") if fdc_input else None
    if model:
        cmd.extend(["--model", str(model)])
    _run_cmd(cmd, cwd=fdc_dir)


def _load_inline(
    inline_dir: Path,
    run_agents: bool,
    model: str,
    inline_input: dict[str, Any] | None,
) -> dict[str, Any]:
    result_path = inline_dir / "inline_result.json"
    result = _read_json(result_path)
    inline_csv = inline_input.get("csv") if inline_input else None
    inline_spec = inline_input.get("spec") if inline_input else None
    inline_notes = inline_input.get("notes") if inline_input else None
    inline_tolerance = inline_input.get("alignment_tolerance") if inline_input else None
    inline_model = inline_input.get("model") if inline_input else None

    if not result and run_agents:
        cmd = ["python", "agent.py", "--model", inline_model or model]
        if inline_csv:
            cmd.extend(["--csv", str(inline_csv)])
        if inline_spec:
            cmd.extend(["--spec", str(inline_spec)])
        if inline_notes:
            cmd.extend(["--notes", str(inline_notes)])
        if inline_tolerance is not None:
            cmd.extend(["--alignment-tolerance", str(inline_tolerance)])
        stdout = _run_cmd(cmd, cwd=inline_dir)
        try:
            result = json.loads(stdout)
            _write_json(result_path, result)
        except json.JSONDecodeError:
            result = None

    report_status = (
        _parse_report_status(inline_dir / "report.md")
        or _parse_report_status(inline_dir / "REPORT.md")
    )

    summary = {
        "status": "UNKNOWN",
        "reason": "",
        "spec_out_strings": [],
        "spec_limits": {},
        "comparison_rows": [],
        "data_paths": {
            "csv": str(inline_csv or inline_dir / "sample_inline_fail.csv"),
            "spec": str(inline_spec or inline_dir / "sample_spec.csv"),
            "notes": str(inline_notes) if inline_notes else "",
        },
    }

    if result:
        llm_result = result.get("llm_result", {})
        payload = result.get("analysis_payload", {})
        summary.update(
            {
                "status": llm_result.get("status", "UNKNOWN"),
                "reason": llm_result.get("reason", ""),
                "spec_out_strings": payload.get("spec_out_strings", []),
                "spec_limits": payload.get("spec_limits", {}),
                "comparison_rows": payload.get("comparison_rows", []),
            }
        )
    elif report_status:
        summary["status"] = report_status.get("status", "UNKNOWN")
        summary["reason"] = report_status.get("reason", "")
    return summary


def _load_defect(defect_dir: Path, defect_input: dict[str, Any] | None) -> dict[str, Any]:
    report_status = (
        _parse_report_status(defect_dir / "report.md")
        or _parse_report_status(defect_dir / "REPORT.md")
        or {"status": "UNKNOWN", "reason": ""}
    )
    data_csv = defect_input.get("data_csv") if defect_input else None
    if not data_csv:
        data_csv = defect_dir / "defect_data.csv"
    spec_total = defect_input.get("spec_total") if defect_input else None
    spec_dr = defect_input.get("spec_dr") if defect_input else None
    if spec_total is None:
        spec_total = 100
    if spec_dr is None:
        spec_dr = 50
    images_base = defect_input.get("images_base") if defect_input else None
    if not images_base:
        images_base = data_csv.parent
    composite_horizontal = (
        defect_input.get("composite_horizontal") if defect_input else None
    ) or (defect_dir / "composite_horizontal.png")
    composite_vertical = (
        defect_input.get("composite_vertical") if defect_input else None
    ) or (defect_dir / "composite_vertical.png")

    rows: list[dict[str, Any]] = []
    if data_csv.exists():
        import csv

        with data_csv.open(newline="") as handle:
            rows = list(csv.DictReader(handle))

    current_rows = [r for r in rows if r.get("run_id") == "current_run"]
    flagged = []
    for row in current_rows:
        total = float(row.get("total_count", 0))
        dr = float(row.get("dr_count", 0))
        if total > spec_total or dr > spec_dr:
            image_file = row.get("image_file", "")
            image_path = Path(image_file)
            if image_file and not image_path.is_absolute():
                image_path = images_base / image_file
            flagged.append(
                {
                    "map_id": row.get("map_id"),
                    "total_count": total,
                    "dr_count": dr,
                    "image_file": image_file,
                    "image_path": str(image_path) if image_file else "",
                }
            )

    return {
        "status": report_status.get("status", "UNKNOWN"),
        "reason": report_status.get("reason", ""),
        "spec": {"total_count": spec_total, "dr_count": spec_dr},
        "flagged_maps": flagged,
        "composite_horizontal": str(composite_horizontal),
        "composite_vertical": str(composite_vertical),
        "data_csv": str(data_csv),
    }


def _load_fdc(fdc_dir: Path, fdc_input: dict[str, Any] | None) -> dict[str, Any]:
    report_status = (
        _parse_report_status(fdc_dir / "report.md")
        or _parse_report_status(fdc_dir / "REPORT.md")
        or {"status": "UNKNOWN", "reason": ""}
    )
    fail_csv = fdc_input.get("fail_csv") if fdc_input else None
    if not fail_csv:
        fail_csv = fdc_dir / "taq_fail.csv"
    fail_param = ""
    fail_step = ""
    if fail_csv.exists():
        import csv

        with fail_csv.open(newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            if rows:
                fail_param = rows[0].get("parameter", "")
                fail_step = rows[0].get("step_no", "")

    timeseries_csv = fdc_input.get("timeseries_csv") if fdc_input else None
    trend_images_csv = fdc_input.get("trend_images_csv") if fdc_input else None
    composite_horizontal = (
        fdc_input.get("composite_horizontal") if fdc_input else None
    ) or (fdc_dir / "composite_horizontal.png")
    composite_vertical = (
        fdc_input.get("composite_vertical") if fdc_input else None
    ) or (fdc_dir / "composite_vertical.png")

    return {
        "status": report_status.get("status", "UNKNOWN"),
        "reason": report_status.get("reason", ""),
        "fail_parameter": fail_param,
        "fail_step_no": fail_step,
        "composite_horizontal": str(composite_horizontal),
        "composite_vertical": str(composite_vertical),
        "timeseries_csv": str(timeseries_csv or fdc_dir / "timeseries.csv"),
        "trend_images_csv": str(trend_images_csv or fdc_dir / "trend_images.csv"),
    }


def _overall_status(statuses: list[str]) -> str:
    if any(s == "FAIL" for s in statuses):
        return "FAIL"
    if any(s == "UNKNOWN" for s in statuses):
        return "UNKNOWN"
    return "PASS"


def _build_overall_payload(
    inline: dict[str, Any],
    defect: dict[str, Any],
    fdc: dict[str, Any],
) -> dict[str, Any]:
    return {
        "inline": {
            "status": inline.get("status"),
            "reason": inline.get("reason"),
            "spec_out": inline.get("spec_out_strings", []),
            "spec_limits": inline.get("spec_limits", {}),
        },
        "defect": {
            "status": defect.get("status"),
            "reason": defect.get("reason"),
            "spec": defect.get("spec", {}),
            "flagged_maps": defect.get("flagged_maps", []),
        },
        "fdc": {
            "status": fdc.get("status"),
            "reason": fdc.get("reason"),
            "fail_parameter": fdc.get("fail_parameter"),
            "fail_step_no": fdc.get("fail_step_no"),
        },
    }


def _write_markdown(path: Path, data: dict[str, Any]) -> None:
    inline = data["inline"]
    defect = data["defect"]
    fdc = data["fdc"]

    lines = [
        "# Combined Report",
        "",
        "## Overall Status",
        f"- Status: {data['overall_status']}",
        f"- Reason: {data.get('overall_reason', '')}",
        f"- Method: {data.get('overall_method', '')}",
        "",
        "## Inline",
        f"- Status: {inline['status']}",
        f"- Reason: {inline['reason']}",
        f"- Data: `{inline['data_paths']['csv']}`",
        f"- Spec: `{inline['data_paths']['spec']}`",
    ]
    if inline["spec_out_strings"]:
        lines.append("- Spec-out:")
        for item in inline["spec_out_strings"]:
            lines.append(f"  - {item}")

    lines.extend(
        [
            "",
            "## Defect",
            f"- Status: {defect['status']}",
            f"- Reason: {defect['reason']}",
            f"- Data: `{defect['data_csv']}`",
            f"- Spec: total_count <= {defect['spec']['total_count']}, dr_count <= {defect['spec']['dr_count']}",
            "",
            "### Defect Composites",
            f"![defect horizontal]({defect['composite_horizontal']})",
            f"![defect vertical]({defect['composite_vertical']})",
        ]
    )
    if defect["flagged_maps"]:
        lines.append("")
        lines.append("### Flagged Maps (current_run)")
        for item in defect["flagged_maps"]:
            image_path = item.get("image_path") or item.get("image_file") or ""
            lines.append(
                f"- {item['map_id']}: total={item['total_count']}, dr={item['dr_count']} "
                f"(`{image_path}`)"
            )
            if image_path:
                lines.append(f"![{item['map_id']}]({image_path})")

    lines.extend(
        [
            "",
            "## FDC",
            f"- Status: {fdc['status']}",
            f"- Reason: {fdc['reason']}",
            f"- Fail: {fdc['fail_parameter']} / step {fdc['fail_step_no']}",
            f"- Data: `{fdc['timeseries_csv']}`",
            f"- Images: `{fdc['trend_images_csv']}`",
            "",
            "### FDC Composites",
            f"![fdc horizontal]({fdc['composite_horizontal']})",
            f"![fdc vertical]({fdc['composite_vertical']})",
        ]
    )

    lines.extend(
        [
            "",
            "## Highlights",
            "- Inline: spec-out metrics listed above (if any).",
            "- Defect: flagged current_run maps listed and composite images shown.",
            "- FDC: fail parameter/step focus with composite images.",
        ]
    )

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Combined report generator.")
    parser.add_argument("--inline-dir", default="inline", help="Inline agent folder.")
    parser.add_argument("--defect-dir", default="defect", help="Defect agent folder.")
    parser.add_argument("--fdc-dir", default="fdc", help="FDC agent folder.")
    parser.add_argument("--input-manifest", default="", help="Optional input manifest JSON.")
    parser.add_argument("--output", default="combined_report.md", help="Output markdown file.")
    parser.add_argument("--output-json", default="combined_report.json", help="Output JSON file.")
    parser.add_argument("--run-agents", action="store_true", help="Run inline agent if result missing.")
    parser.add_argument("--model", default="gpt-5-mini", help="Model for inline agent if run.")
    parser.add_argument("--overall-model", default="", help="Model for overall LLM judgement.")
    parser.add_argument("--no-llm-final", action="store_true", help="Skip LLM overall judgement.")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    project_root = base_dir.parent
    inline_dir = _resolve_dir(args.inline_dir, project_root)
    defect_dir = _resolve_dir(args.defect_dir, project_root)
    fdc_dir = _resolve_dir(args.fdc_dir, project_root)

    manifest_path = Path(args.input_manifest) if args.input_manifest else None
    manifest = _load_manifest(manifest_path) if manifest_path else {}
    inline_input = manifest.get("inline")
    defect_input = manifest.get("defect")
    fdc_input = manifest.get("fdc")

    scratch_dir = base_dir / "_inputs"
    if args.run_agents:
        _run_inline_agent(inline_dir, inline_input, args.model)
        _run_defect_agent(defect_dir, defect_input, scratch_dir)
        _run_fdc_agent(fdc_dir, fdc_input, scratch_dir)

    inline_summary = _load_inline(inline_dir, False, args.model, inline_input)
    defect_summary = _load_defect(defect_dir, defect_input)
    fdc_summary = _load_fdc(fdc_dir, fdc_input)

    heuristic_status = _overall_status(
        [inline_summary["status"], defect_summary["status"], fdc_summary["status"]]
    )
    overall_payload = _build_overall_payload(inline_summary, defect_summary, fdc_summary)
    overall_status = heuristic_status
    overall_reason = "Heuristic summary of component statuses."
    overall_method = "heuristic"
    if not args.no_llm_final:
        try:
            overall_model = args.overall_model or args.model
            llm_result = _llm_overall_judge(overall_payload, overall_model)
            overall_status = llm_result["status"]
            overall_reason = llm_result["reason"]
            overall_method = "llm"
        except Exception as exc:
            overall_status = heuristic_status
            overall_reason = f"LLM failed, fallback to heuristic. {exc}"
            overall_method = "heuristic_fallback"
    result = {
        "overall_status": overall_status,
        "overall_reason": overall_reason,
        "overall_method": overall_method,
        "inline": inline_summary,
        "defect": defect_summary,
        "fdc": fdc_summary,
    }

    output_path = base_dir / args.output
    output_json = base_dir / args.output_json
    _write_markdown(output_path, result)
    _write_json(output_json, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
