"""
Single-file FDC judgement agent.
Reads time-series CSV + trend images, builds composites, compares current vs peers/history twice.
Generates report.md on run. Sample data can be generated with --generate-samples.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import math
import os
import random
import statistics
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

RUN_CURRENT = "current_run"
PEER_PREFIX = "peer_tool"
HISTORY_PREFIX = "history_run"
PARAMETERS = [
    "param_temp",
    "param_pressure",
    "param_flow",
    "param_power",
    "param_voltage",
    "param_speed",
]
STEP_COUNT = 12
STEP_DURATION = 300  # seconds
TOTAL_DURATION = STEP_COUNT * STEP_DURATION

IMAGE_SIZE = (320, 200)
CSV_TS_COLUMNS = ("run_id", "parameter", "t", "step_no", "value")
CSV_IMG_COLUMNS = ("run_id", "parameter", "image_file")
CSV_FAIL_COLUMNS = ("parameter", "step_no")

SIMILARITY_THRESHOLD = 1.6

os.environ.setdefault(
    "OPENAI_API_KEY",
    "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",
)


def _parse_llm_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def _seeded_rng(seed: str) -> random.Random:
    rng = random.Random()
    rng.seed(hash(seed) % 10_000_000)
    return rng


def _draw_label(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int]) -> None:
    font = ImageFont.load_default()
    x, y = xy
    text_w, text_h = draw.textbbox((0, 0), text, font=font)[2:]
    padding = 4
    draw.rectangle(
        [x, y, x + text_w + padding * 2, y + text_h + padding * 2],
        fill=(20, 20, 20),
    )
    draw.text((x + padding, y + padding), text, fill=(245, 245, 245), font=font)


def _render_trend_image(values: list[float], fail_step: int, label: str) -> Image.Image:
    width, height = IMAGE_SIZE
    margin = 12
    span_w = width - margin * 2
    span_h = height - margin * 2

    if not values:
        raise ValueError("Empty series for trend image.")

    vmin = min(values)
    vmax = max(values)
    if vmin == vmax:
        vmax = vmin + 1.0

    img = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    fail_start = (fail_step - 1) * STEP_DURATION
    fail_end = fail_step * STEP_DURATION
    fx0 = margin + int((fail_start / (TOTAL_DURATION - 1)) * span_w)
    fx1 = margin + int((fail_end / (TOTAL_DURATION - 1)) * span_w)
    draw.rectangle((fx0, margin, fx1, margin + span_h), fill=(255, 235, 150, 90))

    for s in range(1, STEP_COUNT):
        x = margin + int((s * STEP_DURATION / (TOTAL_DURATION - 1)) * span_w)
        draw.line((x, margin, x, margin + span_h), fill=(220, 220, 220, 255))

    sample_count = span_w
    indices = [
        int(i * (len(values) - 1) / max(1, sample_count - 1)) for i in range(sample_count)
    ]
    points = []
    for idx in indices:
        v = values[idx]
        x = margin + int((idx / (len(values) - 1)) * span_w)
        y = margin + int((vmax - v) / (vmax - vmin) * span_h)
        points.append((x, y))

    draw.line(points, fill=(28, 96, 212, 255), width=2)
    _draw_label(draw, label, (6, 6))
    return img.convert("RGB")


def _read_fail_info(path: Path) -> tuple[str, int]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Fail CSV missing header row.")
        missing = set(CSV_FAIL_COLUMNS) - set(reader.fieldnames)
        if missing:
            raise ValueError(f"Fail CSV missing columns: {', '.join(sorted(missing))}")

        rows = list(reader)
        if not rows:
            raise ValueError("Fail CSV is empty.")
        parameter = rows[0]["parameter"].strip()
        step_no = int(rows[0]["step_no"])
        return parameter, step_no


def _read_timeseries(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Timeseries CSV missing header row.")
        missing = set(CSV_TS_COLUMNS) - set(reader.fieldnames)
        if missing:
            raise ValueError(f"Timeseries CSV missing columns: {', '.join(sorted(missing))}")

        rows: list[dict[str, Any]] = []
        for row in reader:
            rows.append(
                {
                    "run_id": row["run_id"].strip(),
                    "parameter": row["parameter"].strip(),
                    "t": int(row["t"]),
                    "step_no": int(row["step_no"]),
                    "value": float(row["value"]),
                }
            )
        return rows


def _read_image_map(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Image map CSV missing header row.")
        missing = set(CSV_IMG_COLUMNS) - set(reader.fieldnames)
        if missing:
            raise ValueError(f"Image map CSV missing columns: {', '.join(sorted(missing))}")

        rows: list[dict[str, str]] = []
        for row in reader:
            rows.append(
                {
                    "run_id": row["run_id"].strip(),
                    "parameter": row["parameter"].strip(),
                    "image_file": row["image_file"].strip(),
                }
            )
        return rows


def _split_runs(run_ids: list[str]) -> tuple[list[str], list[str]]:
    peers = sorted([rid for rid in run_ids if rid.startswith(PEER_PREFIX)])
    history = sorted([rid for rid in run_ids if rid.startswith(HISTORY_PREFIX)])
    return peers, history


def _build_run_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    run_map: dict[str, dict[str, str]] = {}
    for row in rows:
        run_map.setdefault(row["run_id"], {})[row["parameter"]] = row["image_file"]
    return run_map


def _build_run_grid(
    run_id: str,
    run_map: dict[str, dict[str, str]],
    base_dir: Path,
    parameters: list[str],
) -> Image.Image:
    grid_w, grid_h = IMAGE_SIZE
    padding = 8
    cols = max(1, math.ceil(math.sqrt(len(parameters))))
    rows = math.ceil(len(parameters) / cols)

    grid_img = Image.new(
        "RGB",
        (grid_w * cols + padding * (cols - 1), grid_h * rows + padding * (rows - 1)),
        (255, 255, 255),
    )
    draw = ImageDraw.Draw(grid_img)

    for idx, param in enumerate(parameters):
        row = idx // cols
        col = idx % cols
        x = col * (grid_w + padding)
        y = row * (grid_h + padding)

        image_rel = run_map.get(run_id, {}).get(param)
        if image_rel:
            img_path = base_dir / image_rel
            tile = Image.open(img_path)
            grid_img.paste(tile, (x, y))
        else:
            draw.rectangle((x, y, x + grid_w, y + grid_h), fill=(235, 235, 235))
            _draw_label(draw, "missing", (x + 6, y + 6))

        _draw_label(draw, param, (x + 6, y + 24))

    _draw_label(draw, run_id, (6, 6))
    return grid_img


def _stack_grids(
    run_ids: list[str],
    run_map: dict[str, dict[str, str]],
    base_dir: Path,
    out_path: Path,
    parameters: list[str],
) -> Path:
    grids = [_build_run_grid(run_id, run_map, base_dir, parameters) for run_id in run_ids]
    padding = 12
    width = max(grid.width for grid in grids)
    height = sum(grid.height for grid in grids) + padding * (len(grids) - 1)

    composite = Image.new("RGB", (width, height), (255, 255, 255))
    y_offset = 0
    for grid in grids:
        composite.paste(grid, (0, y_offset))
        y_offset += grid.height + padding

    composite.save(out_path)
    return out_path


def _summarize_fail_step(
    rows: list[dict[str, Any]],
    fail_param: str,
    fail_step: int,
) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["parameter"] != fail_param:
            continue
        grouped.setdefault(row["run_id"], []).append(row)

    summary: dict[str, dict[str, float]] = {}
    for run_id, run_rows in grouped.items():
        fail_vals = [r["value"] for r in run_rows if r["step_no"] == fail_step]
        base_vals = [r["value"] for r in run_rows if r["step_no"] != fail_step]
        mean_fail = statistics.mean(fail_vals)
        mean_base = statistics.mean(base_vals)
        std_fail = statistics.pstdev(fail_vals) if len(fail_vals) > 1 else 0.0

        slope = 0.0
        if len(fail_vals) > 2:
            xs = [r["t"] % STEP_DURATION for r in run_rows if r["step_no"] == fail_step]
            x_mean = statistics.mean(xs)
            y_mean = statistics.mean(fail_vals)
            num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, fail_vals))
            den = sum((x - x_mean) ** 2 for x in xs) or 1.0
            slope = num / den

        summary[run_id] = {
            "fail_mean": round(mean_fail, 3),
            "base_mean": round(mean_base, 3),
            "delta": round(mean_fail - mean_base, 3),
            "fail_std": round(std_fail, 3),
            "fail_slope": round(slope, 6),
        }
    return summary


def _build_payload(
    fail_param: str,
    fail_step: int,
    run_summary: dict[str, dict[str, float]],
) -> dict[str, Any]:
    return {
        "fail_parameter": fail_param,
        "fail_step_no": fail_step,
        "run_summary": run_summary,
        "step_count": STEP_COUNT,
        "step_duration_sec": STEP_DURATION,
    }


def _encode_image(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def _llm_judge(
    composite_path: Path,
    payload: dict[str, Any],
    mode: str,
    model: str,
    engineer_notes: str,
) -> dict[str, str]:
    system_prompt = (
        "너는 FDC 판정 에이전트다. "
        "이미지와 데이터로 current vs peers/history를 비교한다. "
        "유사한 패턴/경향이 있으면 PASS, 없으면 FAIL. "
        "반드시 JSON만 출력하라."
    )
    user_prompt = (
        f"비교 모드: {mode}\n\n"
        "엔지니어 노트:\n"
        f"{engineer_notes or '(없음)'}\n\n"
        "데이터:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        '출력 형식: {"status": "PASS|FAIL", "reason": "한국어 설명"}'
    )

    llm = ChatOpenAI(model=model, temperature=1)
    response = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=[
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": _encode_image(composite_path)}},
                ]
            ),
        ]
    )
    result = _parse_llm_json(response.content or "")
    status = str(result.get("status", "")).upper()
    reason = str(result.get("reason", "")).strip()
    if status not in {"PASS", "FAIL"}:
        raise ValueError(f"LLM output missing status PASS/FAIL: {result}")
    if not reason:
        raise ValueError("LLM output missing reason.")
    return {"status": status, "reason": reason}


def _llm_final_judge(
    composite_horizontal: Path,
    composite_vertical: Path,
    payload: dict[str, Any],
    horizontal_result: dict[str, str],
    vertical_result: dict[str, str],
    model: str,
    engineer_notes: str,
) -> dict[str, str]:
    system_prompt = (
        "너는 FDC 최종 판정 에이전트다. "
        "수평/수직 비교 결과와 이미지, 데이터를 종합해 최종 PASS/FAIL을 판단한다. "
        "유사 패턴/경향이 하나라도 명확하면 PASS 가능. "
        "근거가 부족하면 FAIL. "
        "반드시 JSON만 출력하라."
        "엔니지어 노트를 절대적으로 반영해라."
    )
    user_prompt = (
        "수평/수직 결과와 데이터, 이미지 모두 참고해서 최종 판정을 내려라.\n\n"
        "엔지니어 노트:\n"
        f"{engineer_notes or '(없음)'}\n\n"
        "수평 결과:\n"
        f"{json.dumps(horizontal_result, ensure_ascii=False)}\n\n"
        "수직 결과:\n"
        f"{json.dumps(vertical_result, ensure_ascii=False)}\n\n"
        "데이터:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        '출력 형식: {"status": "PASS|FAIL", "reason": "한국어 설명"}'
    )

    llm = ChatOpenAI(model=model, temperature=1)
    response = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=[
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": _encode_image(composite_horizontal)}},
                    {"type": "image_url", "image_url": {"url": _encode_image(composite_vertical)}},
                ]
            ),
        ]
    )
    result = _parse_llm_json(response.content or "")
    status = str(result.get("status", "")).upper()
    reason = str(result.get("reason", "")).strip()
    if status not in {"PASS", "FAIL"}:
        raise ValueError(f"LLM output missing status PASS/FAIL: {result}")
    if not reason:
        raise ValueError("LLM output missing reason.")
    return {"status": status, "reason": reason}


def _heuristic_judge(
    run_summary: dict[str, dict[str, float]],
    current: str,
    compare_ids: list[str],
) -> dict[str, str]:
    def vector(stats: dict[str, float]) -> list[float]:
        return [
            stats["delta"],
            stats["fail_std"],
            stats["fail_slope"] * 1000.0,
        ]

    current_vec = vector(run_summary[current])
    best_distance = None
    best_id = None
    for run_id in compare_ids:
        other_vec = vector(run_summary[run_id])
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(current_vec, other_vec)))
        if best_distance is None or dist < best_distance:
            best_distance = dist
            best_id = run_id

    status = "PASS" if best_distance is not None and best_distance <= SIMILARITY_THRESHOLD else "FAIL"
    reason = (
        f"Closest match: {best_id} (distance={best_distance:.2f})"
        if best_distance is not None
        else "No comparison available."
    )
    return {"status": status, "reason": reason}


def _write_report(
    report_path: Path,
    horizontal_result: dict[str, str],
    vertical_result: dict[str, str],
    final_result: dict[str, str],
    payload: dict[str, Any],
    method: str,
    engineer_notes: str,
) -> None:
    lines = [
        "# FDC Judgement Report",
        "",
        "## Inputs",
        "- composite_horizontal.png",
        "- composite_vertical.png",
        "- timeseries.csv",
        "- trend_images.csv",
        "- taq_fail.csv",
        "",
        "## Fail Focus",
        f"- parameter: {payload['fail_parameter']}",
        f"- step_no: {payload['fail_step_no']}",
        "",
        "## Engineer Notes",
        engineer_notes or "(none)",
        "",
        "## Horizontal Comparison (current vs peers)",
        f"- Status: {horizontal_result['status']}",
        f"- Reason: {horizontal_result['reason']}",
        "",
        "## Vertical Comparison (current vs history)",
        f"- Status: {vertical_result['status']}",
        f"- Reason: {vertical_result['reason']}",
        "",
        "## Final Decision",
        f"- Status: {final_result['status']}",
        f"- Reason: {final_result['reason']}",
        f"- Method: {method}",
        "",
        "## Run Summary (fail step stats)",
    ]

    for run_id, stats in payload["run_summary"].items():
        lines.append(f"- {run_id}: {stats}")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    upper_path = report_path.with_name("REPORT.md")
    if upper_path != report_path:
        upper_path.write_text("\n".join(lines), encoding="utf-8")


def generate_samples(base_dir: Path) -> None:
    images_dir = base_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    fail_param = "param_pressure"
    fail_step = 7

    run_profiles = {
        "current_run": {"bias": 0.0, "anomaly": 5.5},
        "peer_tool_1": {"bias": -0.2, "anomaly": 4.4},
        "peer_tool_2": {"bias": 0.6, "anomaly": 0.0},
        "history_run_1": {"bias": 0.8, "anomaly": 0.0},
        "history_run_2": {"bias": 0.1, "anomaly": 5.0},
        "history_run_3": {"bias": -0.5, "anomaly": 0.0},
    }

    param_base = {
        "param_temp": 100.0,
        "param_pressure": 48.0,
        "param_flow": 200.0,
        "param_power": 320.0,
        "param_voltage": 24.0,
        "param_speed": 1500.0,
    }
    step_pattern = [0.0, 0.2, 0.1, -0.1, -0.2, 0.0, 0.15, 0.3, 0.1, -0.05, 0.0, 0.2]
    param_scale = {
        "param_temp": 0.8,
        "param_pressure": 1.0,
        "param_flow": 0.5,
        "param_power": 0.6,
        "param_voltage": 0.15,
        "param_speed": 2.5,
    }
    param_drift = {
        "param_temp": 0.15,
        "param_pressure": 0.2,
        "param_flow": 0.1,
        "param_power": 0.12,
        "param_voltage": 0.05,
        "param_speed": 0.8,
    }

    ts_rows: list[dict[str, Any]] = []
    image_rows: list[dict[str, str]] = []

    for run_id, profile in run_profiles.items():
        for param in PARAMETERS:
            rng = _seeded_rng(f"{run_id}-{param}")
            base = param_base[param] + profile["bias"]
            series: list[float] = []
            for t in range(TOTAL_DURATION):
                step_no = t // STEP_DURATION + 1
                offset = step_pattern[step_no - 1] * param_scale[param]
                drift = (t % STEP_DURATION) / STEP_DURATION * param_drift[param]
                value = base + offset + drift + rng.gauss(0.0, 0.25)
                if param == fail_param and step_no == fail_step:
                    value += profile["anomaly"]

                series.append(value)
                ts_rows.append(
                    {
                        "run_id": run_id,
                        "parameter": param,
                        "t": t,
                        "step_no": step_no,
                        "value": round(value, 6),
                    }
                )

            img = _render_trend_image(series, fail_step, f"{run_id}:{param}")
            file_name = f"{run_id}_{param}.png"
            img.save(images_dir / file_name)
            image_rows.append(
                {
                    "run_id": run_id,
                    "parameter": param,
                    "image_file": f"images/{file_name}",
                }
            )

    timeseries_csv = base_dir / "timeseries.csv"
    with timeseries_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_TS_COLUMNS)
        writer.writeheader()
        writer.writerows(ts_rows)

    images_csv = base_dir / "trend_images.csv"
    with images_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_IMG_COLUMNS)
        writer.writeheader()
        writer.writerows(image_rows)

    fail_csv = base_dir / "taq_fail.csv"
    with fail_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FAIL_COLUMNS)
        writer.writeheader()
        writer.writerow({"parameter": fail_param, "step_no": fail_step})

    notes_path = base_dir / "engineer_notes_sample.txt"
    if not notes_path.exists():
        notes_path.write_text(
            "PASS 가능 기준: 동일 step에서 유사한 드리프트/피크/노이즈 패턴이 peer/history에 존재.\n"
            "Fail step 중심으로 trend shape(증가/감소/oscillation)를 우선 비교.\n"
            "근거 부족하거나 방향성 불일치 시 FAIL 유지.\n",
            encoding="utf-8",
        )

    run_map = _build_run_map(image_rows)
    peers, history = _split_runs(list(run_profiles.keys()))
    _stack_grids(
        [RUN_CURRENT, *peers],
        run_map,
        base_dir,
        base_dir / "composite_horizontal.png",
        PARAMETERS,
    )
    _stack_grids(
        [RUN_CURRENT, *history],
        run_map,
        base_dir,
        base_dir / "composite_vertical.png",
        PARAMETERS,
    )

    run_summary = _summarize_fail_step(ts_rows, fail_param, fail_step)
    payload = _build_payload(fail_param, fail_step, run_summary)
    horizontal_result = _heuristic_judge(run_summary, RUN_CURRENT, peers)
    vertical_result = _heuristic_judge(run_summary, RUN_CURRENT, history)
    final_status = (
        "PASS" if "PASS" in {horizontal_result["status"], vertical_result["status"]} else "FAIL"
    )
    final_result = {
        "status": final_status,
        "reason": "Heuristic OR of horizontal/vertical results.",
    }
    _write_report(
        base_dir / "report.md",
        horizontal_result,
        vertical_result,
        final_result,
        payload,
        "heuristic",
        notes_path.read_text(encoding="utf-8"),
    )


def run_agent(
    base_dir: Path,
    timeseries_csv: Path,
    images_csv: Path,
    fail_csv: Path,
    notes_path: Path,
    model: str,
    use_llm: bool,
) -> dict[str, Any]:
    fail_param, fail_step = _read_fail_info(fail_csv)
    ts_rows = _read_timeseries(timeseries_csv)
    image_rows = _read_image_map(images_csv)

    run_ids = sorted({row["run_id"] for row in ts_rows})
    if RUN_CURRENT not in run_ids:
        raise ValueError("Timeseries CSV missing current_run.")
    peers, history = _split_runs(run_ids)
    if not peers or not history:
        raise ValueError("Timeseries CSV must include peer_tool_* and history_run_* runs.")

    run_summary = _summarize_fail_step(ts_rows, fail_param, fail_step)
    payload = _build_payload(fail_param, fail_step, run_summary)
    run_map = _build_run_map(image_rows)
    engineer_notes = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""

    composite_horizontal = base_dir / "composite_horizontal.png"
    composite_vertical = base_dir / "composite_vertical.png"
    _stack_grids([RUN_CURRENT, *peers], run_map, base_dir, composite_horizontal, PARAMETERS)
    _stack_grids([RUN_CURRENT, *history], run_map, base_dir, composite_vertical, PARAMETERS)

    if use_llm:
        horizontal_result = _llm_judge(composite_horizontal, payload, "horizontal", model, engineer_notes)
        vertical_result = _llm_judge(composite_vertical, payload, "vertical", model, engineer_notes)
        final_result = _llm_final_judge(
            composite_horizontal,
            composite_vertical,
            payload,
            horizontal_result,
            vertical_result,
            model,
            engineer_notes,
        )
        method = "llm"
    else:
        horizontal_result = _heuristic_judge(run_summary, RUN_CURRENT, peers)
        vertical_result = _heuristic_judge(run_summary, RUN_CURRENT, history)
        final_status = (
            "PASS"
            if "PASS" in {horizontal_result["status"], vertical_result["status"]}
            else "FAIL"
        )
        final_result = {
            "status": final_status,
            "reason": "Heuristic OR of horizontal/vertical results.",
        }
        method = "heuristic"

    _write_report(
        base_dir / "report.md",
        horizontal_result,
        vertical_result,
        final_result,
        payload,
        method,
        engineer_notes,
    )
    return {
        "horizontal": horizontal_result,
        "vertical": vertical_result,
        "final": final_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="FDC judgement agent.")
    parser.add_argument("--generate-samples", action="store_true", help="Generate sample images/data.")
    parser.add_argument("--timeseries", default="timeseries.csv", help="Path to timeseries CSV.")
    parser.add_argument("--images", default="trend_images.csv", help="Path to trend images CSV.")
    parser.add_argument("--fail", default="taq_fail.csv", help="Path to taq fail CSV.")
    parser.add_argument(
        "--engineer-notes-file",
        default="engineer_notes_sample.txt",
        help="Path to engineer notes text file.",
    )
    parser.add_argument("--model", default="gpt-4o-mini", help="LLM model name.")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM and use heuristic.")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    if args.generate_samples:
        generate_samples(base_dir)
        return

    timeseries_csv = base_dir / args.timeseries
    images_csv = base_dir / args.images
    fail_csv = base_dir / args.fail
    notes_path = base_dir / args.engineer_notes_file
    if not timeseries_csv.exists() or not images_csv.exists() or not fail_csv.exists():
        generate_samples(base_dir)

    result = run_agent(
        base_dir=base_dir,
        timeseries_csv=timeseries_csv,
        images_csv=images_csv,
        fail_csv=fail_csv,
        notes_path=notes_path,
        model=args.model,
        use_llm=not args.no_llm,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
