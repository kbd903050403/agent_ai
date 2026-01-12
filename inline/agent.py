"""
Single-file FDC inline agent.
Reads inline CSV + spec CSV + engineer notes, builds payload, and asks LLM for PASS/FAIL.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

INLINE_COLUMNS = ("thickness", "range", "edge_thk", "edge_range")
PEER_PREFIX = "peer_tool"
HISTORY_PREFIX = "history_run"

os.environ.setdefault(
    "OPENAI_API_KEY",
    "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",
)


def _parse_llm_json(text: str) -> dict[str, str]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def _split_runs(
    datasets: dict[str, list[dict[str, float]]],
) -> tuple[list[dict[str, float]] | None, list[tuple[str, list[dict[str, float]]]], list[tuple[str, list[dict[str, float]]]]]:
    current = datasets.get("current_run")
    peer_runs = sorted(
        [
            (name, samples)
            for name, samples in datasets.items()
            if name.startswith(PEER_PREFIX)
        ],
        key=lambda item: item[0],
    )
    history_runs = sorted(
        [
            (name, samples)
            for name, samples in datasets.items()
            if name.startswith(HISTORY_PREFIX)
        ],
        key=lambda item: item[0],
    )
    return current, peer_runs, history_runs


def _read_inline_csv(path: Path) -> dict[str, list[dict[str, float]]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV missing header row.")

        required_columns = {"run_id", *INLINE_COLUMNS}
        missing = required_columns - set(reader.fieldnames)
        if missing:
            raise ValueError(f"CSV missing columns: {', '.join(sorted(missing))}")

        datasets: dict[str, list[dict[str, float]]] = {}
        for row in reader:
            run_id = (row.get("run_id") or "").strip()
            if not run_id:
                raise ValueError("CSV row missing run_id.")

            sample: dict[str, float] = {}
            for col in INLINE_COLUMNS:
                value = row.get(col)
                if value is None or value == "":
                    raise ValueError(f"CSV row missing value for '{col}'.")
                sample[col] = float(value)

            datasets.setdefault(run_id, []).append(sample)

    current, peer_runs, history_runs = _split_runs(datasets)
    if not current:
        raise ValueError("CSV missing current_run data.")
    if not peer_runs:
        raise ValueError("CSV missing peer_tool_* runs.")
    if not history_runs:
        raise ValueError("CSV missing history_run_* runs.")
    return datasets


def _read_spec_csv(path: Path) -> dict[str, dict[str, float]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Spec CSV missing header row.")

        required = {"parameter", "spec_min", "spec_max"}
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(f"Spec CSV missing columns: {', '.join(sorted(missing))}")

        spec_limits: dict[str, dict[str, float]] = {}
        for row in reader:
            param = (row.get("parameter") or "").strip()
            if not param:
                raise ValueError("Spec CSV row missing parameter.")
            if param not in INLINE_COLUMNS:
                raise ValueError(f"Unknown parameter in spec CSV: {param}")
            spec_min = row.get("spec_min")
            spec_max = row.get("spec_max")
            if spec_min is None or spec_min == "" or spec_max is None or spec_max == "":
                raise ValueError(f"Spec CSV row missing spec_min/spec_max for {param}.")
            spec_limits[param] = {"min": float(spec_min), "max": float(spec_max)}

    missing_params = [col for col in INLINE_COLUMNS if col not in spec_limits]
    if missing_params:
        raise ValueError(f"Spec CSV missing parameters: {', '.join(missing_params)}")
    for col in INLINE_COLUMNS:
        if spec_limits[col]["min"] > spec_limits[col]["max"]:
            raise ValueError(f"Spec limits for '{col}' min > max.")
    return spec_limits


def _summarize_stats(samples: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    stats: dict[str, dict[str, float]] = {}
    for col in INLINE_COLUMNS:
        values = [row[col] for row in samples]
        stats[col] = {
            "mean": statistics.mean(values),
            "min": min(values),
            "max": max(values),
        }
    return stats


def _build_spec_bounds(
    spec_limits: dict[str, dict[str, float]],
) -> dict[str, dict[str, dict[str, float]]]:
    bounds: dict[str, dict[str, dict[str, float]]] = {}
    for col in INLINE_COLUMNS:
        spec_min = float(spec_limits[col]["min"])
        spec_max = float(spec_limits[col]["max"])
        bounds[col] = {}
        for metric in ("mean", "min", "max"):
            bounds[col][metric] = {"min": spec_min, "max": spec_max}
    return bounds


def _compute_bounds(
    reference_stats: list[dict[str, dict[str, float]]],
) -> dict[str, dict[str, dict[str, float]]]:
    bounds: dict[str, dict[str, dict[str, float]]] = {}
    for col in INLINE_COLUMNS:
        bounds[col] = {}
        for metric in ("mean", "min", "max"):
            metric_values = [stats[col][metric] for stats in reference_stats]
            bounds[col][metric] = {
                "min": min(metric_values),
                "max": max(metric_values),
            }
    return bounds


def _detect_spec_out(
    current_stats: dict[str, dict[str, float]],
    spec_bounds: dict[str, dict[str, dict[str, float]]],
) -> list[dict[str, float | str]]:
    issues: list[dict[str, float | str]] = []
    for col in INLINE_COLUMNS:
        for metric in ("mean", "min", "max"):
            value = current_stats[col][metric]
            spec_min = spec_bounds[col][metric]["min"]
            spec_max = spec_bounds[col][metric]["max"]
            if value < spec_min:
                issues.append(
                    {
                        "parameter": col,
                        "metric": metric,
                        "direction": "below",
                        "value": value,
                        "spec_bound": spec_min,
                    }
                )
            elif value > spec_max:
                issues.append(
                    {
                        "parameter": col,
                        "metric": metric,
                        "direction": "above",
                        "value": value,
                        "spec_bound": spec_max,
                    }
                )
    return issues


def _within_bounds(value: float, bounds: dict[str, float], tolerance: float) -> bool:
    return (bounds["min"] - tolerance) <= value <= (bounds["max"] + tolerance)


def _evaluate_alignment(
    spec_outs: list[dict[str, float | str]],
    vertical_bounds: dict[str, dict[str, dict[str, float]]],
    horizontal_bounds: dict[str, dict[str, dict[str, float]]],
    tolerance: float,
) -> list[dict[str, float | str | bool]]:
    alignments: list[dict[str, float | str | bool]] = []
    for issue in spec_outs:
        col = str(issue["parameter"])
        metric = str(issue["metric"])
        value = float(issue["value"])
        alignments.append(
            {
                "parameter": col,
                "metric": metric,
                "value": value,
                "vertical_match": _within_bounds(value, vertical_bounds[col][metric], tolerance),
                "horizontal_match": _within_bounds(value, horizontal_bounds[col][metric], tolerance),
            }
        )
    return alignments


def _format_spec_out(
    issue: dict[str, float | str],
    alignment: dict[str, float | str | bool],
) -> str:
    direction = "below" if issue["direction"] == "below" else "above"
    bound_label = "spec_min" if direction == "below" else "spec_max"
    value = float(issue["value"])
    bound = float(issue["spec_bound"])
    vertical_match = "yes" if alignment["vertical_match"] else "no"
    horizontal_match = "yes" if alignment["horizontal_match"] else "no"
    return (
        f"{issue['parameter']} {issue['metric']} {direction} {bound_label} "
        f"({bound:.3f} um); current {value:.3f} um; "
        f"vertical match: {vertical_match}; horizontal match: {horizontal_match}"
    )


def _stats_rows(label: str, stats: dict[str, dict[str, float]]) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    for col in INLINE_COLUMNS:
        rows.append(
            {
                "group": label,
                "parameter": col,
                "mean": round(stats[col]["mean"], 3),
                "min": round(stats[col]["min"], 3),
                "max": round(stats[col]["max"], 3),
            }
        )
    return rows


def _bounds_rows(
    bounds: dict[str, dict[str, dict[str, float]]],
    label: str,
) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    for col in INLINE_COLUMNS:
        for metric in ("mean", "min", "max"):
            rows.append(
                {
                    "group": label,
                    "parameter": col,
                    "metric": metric,
                    "min": round(bounds[col][metric]["min"], 3),
                    "max": round(bounds[col][metric]["max"], 3),
                }
            )
    return rows


def _comparison_rows(
    current_stats: dict[str, dict[str, float]],
    spec_bounds: dict[str, dict[str, dict[str, float]]],
    vertical_bounds: dict[str, dict[str, dict[str, float]]],
    horizontal_bounds: dict[str, dict[str, dict[str, float]]],
    spec_outs: list[dict[str, float | str]],
    alignments: list[dict[str, float | str | bool]],
) -> list[dict[str, float | str | bool | None]]:
    alignment_map = {(a["parameter"], a["metric"]): a for a in alignments}
    spec_out_map = {(s["parameter"], s["metric"]): s for s in spec_outs}
    rows: list[dict[str, float | str | bool | None]] = []
    for col in INLINE_COLUMNS:
        for metric in ("mean", "min", "max"):
            current_value = current_stats[col][metric]
            spec_out = (col, metric) in spec_out_map
            alignment = alignment_map.get((col, metric))
            rows.append(
                {
                    "parameter": col,
                    "metric": metric,
                    "current": round(current_value, 3),
                    "spec_min": round(spec_bounds[col][metric]["min"], 3),
                    "spec_max": round(spec_bounds[col][metric]["max"], 3),
                    "vertical_min": round(vertical_bounds[col][metric]["min"], 3),
                    "vertical_max": round(vertical_bounds[col][metric]["max"], 3),
                    "horizontal_min": round(horizontal_bounds[col][metric]["min"], 3),
                    "horizontal_max": round(horizontal_bounds[col][metric]["max"], 3),
                    "spec_out": spec_out,
                    "vertical_match": alignment["vertical_match"] if alignment else None,
                    "horizontal_match": alignment["horizontal_match"] if alignment else None,
                }
            )
    return rows


def _build_payload(
    datasets: dict[str, list[dict[str, float]]],
    spec_limits: dict[str, dict[str, float]],
    alignment_tolerance: float,
) -> dict[str, object]:
    current_samples, peer_runs, history_runs = _split_runs(datasets)
    if current_samples is None:
        raise ValueError("Missing current_run dataset.")

    current_stats = _summarize_stats(current_samples)
    peer_stats = [(name, _summarize_stats(samples)) for name, samples in peer_runs]
    history_stats = [(name, _summarize_stats(samples)) for name, samples in history_runs]

    spec_bounds = _build_spec_bounds(spec_limits)
    vertical_bounds = _compute_bounds([stats for _, stats in history_stats])
    horizontal_bounds = _compute_bounds([stats for _, stats in peer_stats])

    spec_outs = _detect_spec_out(current_stats, spec_bounds)
    alignments = _evaluate_alignment(
        spec_outs,
        vertical_bounds,
        horizontal_bounds,
        alignment_tolerance,
    )
    alignment_map = {(a["parameter"], a["metric"]): a for a in alignments}
    spec_out_strings = [
        _format_spec_out(issue, alignment_map[(issue["parameter"], issue["metric"])])
        for issue in spec_outs
    ]

    stats_row_data = []
    stats_row_data.extend(_stats_rows("current_run", current_stats))
    for name, stats in peer_stats:
        stats_row_data.extend(_stats_rows(name, stats))
    for name, stats in history_stats:
        stats_row_data.extend(_stats_rows(name, stats))

    bounds_row_data = []
    bounds_row_data.extend(_bounds_rows(spec_bounds, "spec"))
    bounds_row_data.extend(_bounds_rows(vertical_bounds, "vertical"))
    bounds_row_data.extend(_bounds_rows(horizontal_bounds, "horizontal"))

    comparison_row_data = _comparison_rows(
        current_stats,
        spec_bounds,
        vertical_bounds,
        horizontal_bounds,
        spec_outs,
        alignments,
    )

    return {
        "spec_out_strings": spec_out_strings,
        "comparison_rows": comparison_row_data,
        "stats_rows": stats_row_data,
        "bounds_rows": bounds_row_data,
        "spec_limits": spec_limits,
        "alignment_tolerance": alignment_tolerance,
        "units": "um",
    }


def _run_llm(payload: dict[str, object], engineer_notes: str, model: str) -> dict[str, str]:
    system_prompt = (
        "너는 반도체 인라인(FDC) 판정 에이전트다. "
        "입력 데이터와 엔지니어 노트를 바탕으로 PASS/FAIL을 판단한다. "
        "spec-out이라도 수직(이전 이력)과 수평(동시간대 동일 RCP 장비) 비교가 "
        "일치하고 엔지니어 노트의 근거가 충분하면 PASS로 판단할 수 있다. "
        "엔지니어 노트를 절대적으로 따라라. "
        "근거가 부족하거나 불일치하면 FAIL을 유지한다. "
        "반드시 JSON만 출력하라."
    )
    user_prompt = (
        "아래 입력을 바탕으로 PASS/FAIL을 판단하라.\n\n"
        "엔지니어 노트:\n"
        f"{engineer_notes or '(없음)'}\n\n"
        "데이터:\n"
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


def run_agent(
    csv_path: Path,
    spec_csv: Path,
    notes_path: Path,
    alignment_tolerance: float = 0.0,
    model: str = "gpt-5-mini",
) -> dict[str, object]:
    datasets = _read_inline_csv(csv_path)
    spec_limits = _read_spec_csv(spec_csv)
    engineer_notes = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""
    payload = _build_payload(datasets, spec_limits, alignment_tolerance)
    llm_result = _run_llm(payload, engineer_notes, model)
    return {
        "analysis_payload": payload,
        "llm_result": llm_result,
    }


def _write_report(
    report_path: Path,
    result: dict[str, object],
    csv_path: Path,
    spec_path: Path,
    notes_path: Path,
    alignment_tolerance: float,
) -> None:
    payload = result.get("analysis_payload", {})
    llm_result = result.get("llm_result", {})
    spec_limits = payload.get("spec_limits", {})
    spec_out_strings = payload.get("spec_out_strings", [])
    comparison_rows = payload.get("comparison_rows", [])

    lines = [
        "# Inline Judgement Report",
        "",
        "## Inputs",
        f"- csv: `{csv_path}`",
        f"- spec: `{spec_path}`",
        f"- engineer_notes: `{notes_path}`",
        f"- alignment_tolerance: {alignment_tolerance}",
        "",
        "## Spec Limits",
    ]
    if isinstance(spec_limits, dict) and spec_limits:
        for key in INLINE_COLUMNS:
            limit = spec_limits.get(key, {})
            if isinstance(limit, dict) and "min" in limit and "max" in limit:
                lines.append(f"- {key}: {limit['min']} ~ {limit['max']}")
    else:
        lines.append("- (없음)")

    lines.append("")
    lines.append("## Spec-Out")
    if spec_out_strings:
        for item in spec_out_strings:
            lines.append(f"- {item}")
    else:
        lines.append("- 없음")

    lines.append("")
    lines.append("## Spec-Out Alignment")
    spec_out_rows = [
        row for row in comparison_rows
        if isinstance(row, dict) and row.get("spec_out")
    ]
    if spec_out_rows:
        for row in spec_out_rows:
            lines.append(
                "- {param} {metric}: current={current}, spec=[{spec_min}, {spec_max}], "
                "vertical_match={v_match}, horizontal_match={h_match}".format(
                    param=row.get("parameter"),
                    metric=row.get("metric"),
                    current=row.get("current"),
                    spec_min=row.get("spec_min"),
                    spec_max=row.get("spec_max"),
                    v_match=row.get("vertical_match"),
                    h_match=row.get("horizontal_match"),
                )
            )
    else:
        lines.append("- 없음")

    lines.extend(
        [
            "",
            "## Final Decision",
            f"- Status: {llm_result.get('status', 'UNKNOWN')}",
            f"- Reason: {llm_result.get('reason', '')}",
            "- Method: llm",
        ]
    )

    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    default_csv = base_dir / "sample_inline_fail.csv"
    default_spec = base_dir / "sample_spec.csv"
    default_notes = base_dir / "engineer_notes_sample.txt"
    default_json = base_dir / "inline_result.json"
    default_report = base_dir / "report.md"

    parser = argparse.ArgumentParser(description="Run the single-file FDC agent.")
    parser.add_argument("--csv", default=str(default_csv), help="Inline CSV path.")
    parser.add_argument("--spec", default=str(default_spec), help="Spec CSV path.")
    parser.add_argument("--notes", default=str(default_notes), help="Engineer notes path.")
    parser.add_argument(
        "--alignment-tolerance",
        type=float,
        default=0.0,
        help="Alignment tolerance.",
    )
    parser.add_argument("--model", default="gpt-5-mini", help="LLM model name.")
    parser.add_argument("--output-json", default=str(default_json), help="JSON output path.")
    parser.add_argument("--report", default=str(default_report), help="Report markdown path.")
    parser.add_argument("--no-output-files", action="store_true", help="Skip writing files.")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    spec_path = Path(args.spec)
    notes_path = Path(args.notes)

    result = run_agent(
        csv_path=csv_path,
        spec_csv=spec_path,
        notes_path=notes_path,
        alignment_tolerance=args.alignment_tolerance,
        model=args.model,
    )
    if not args.no_output_files:
        output_json = Path(args.output_json)
        output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_report(
            Path(args.report),
            result,
            csv_path=csv_path,
            spec_path=spec_path,
            notes_path=notes_path,
            alignment_tolerance=args.alignment_tolerance,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
