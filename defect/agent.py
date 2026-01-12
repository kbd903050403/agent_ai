"""
Single-file Defect judgement agent.
Reads defect CSV + images, builds composite images, compares current vs peers/history twice.
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
MAP_IDS = ["map_1", "map_2", "map_3", "map_4"]
CSV_COLUMNS = ("run_id", "map_id", "image_file", "total_count", "dr_count")

SPEC_TOTAL = 100
SPEC_DR = 50
IMAGE_SIZE = (256, 256)
WAFER_RADIUS = 118

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


def _random_point_in_pattern(
    rng: random.Random,
    cx: float,
    cy: float,
    radius: float,
    pattern: str,
) -> tuple[float, float]:
    angle = rng.uniform(0, math.tau)
    if pattern == "center":
        r = radius * (rng.random() ** 2)
    elif pattern == "ring":
        r = radius * (0.55 + 0.4 * rng.random())
    elif pattern == "edge":
        r = radius * (0.85 + 0.15 * rng.random())
    else:
        r = radius * math.sqrt(rng.random())
    x = cx + r * math.cos(angle)
    y = cy + r * math.sin(angle)
    return x, y


def _render_wafer(
    total_count: int,
    dr_count: int,
    rng: random.Random,
    pattern: str = "random",
) -> Image.Image:
    img = Image.new("RGB", IMAGE_SIZE, (245, 245, 245))
    draw = ImageDraw.Draw(img)
    cx, cy = IMAGE_SIZE[0] / 2, IMAGE_SIZE[1] / 2

    draw.ellipse(
        (cx - WAFER_RADIUS, cy - WAFER_RADIUS, cx + WAFER_RADIUS, cy + WAFER_RADIUS),
        fill=(255, 255, 255),
        outline=(40, 40, 40),
        width=2,
    )

    total_count = max(0, int(total_count))
    dr_count = max(0, min(int(dr_count), total_count))
    dr_indices = set(rng.sample(range(total_count), dr_count)) if total_count else set()

    dot_color = (0, 170, 255)
    for idx in range(total_count):
        x, y = _random_point_in_pattern(rng, cx, cy, WAFER_RADIUS - 4, pattern)
        if idx in dr_indices:
            radius = rng.uniform(2.2, 3.2)
        else:
            radius = rng.uniform(1.4, 2.2)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=dot_color, outline=None)
    return img


def _read_defect_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV missing header row.")
        missing = set(CSV_COLUMNS) - set(reader.fieldnames)
        if missing:
            raise ValueError(f"CSV missing columns: {', '.join(sorted(missing))}")

        rows: list[dict[str, Any]] = []
        for row in reader:
            rows.append(
                {
                    "run_id": row["run_id"].strip(),
                    "map_id": row["map_id"].strip(),
                    "image_file": row["image_file"].strip(),
                    "total_count": int(float(row["total_count"])),
                    "dr_count": int(float(row["dr_count"])),
                }
            )
    return rows


def _split_runs(run_ids: list[str]) -> tuple[list[str], list[str]]:
    peers = sorted([rid for rid in run_ids if rid.startswith(PEER_PREFIX)])
    history = sorted([rid for rid in run_ids if rid.startswith(HISTORY_PREFIX)])
    return peers, history


def _build_run_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    run_map: dict[str, dict[str, str]] = {}
    for row in rows:
        run_map.setdefault(row["run_id"], {})[row["map_id"]] = row["image_file"]
    return run_map


def _build_run_grid(
    run_id: str,
    run_map: dict[str, dict[str, str]],
    base_dir: Path,
    map_ids: list[str],
) -> Image.Image:
    if not map_ids:
        raise ValueError("No map_id values found.")

    grid_w, grid_h = IMAGE_SIZE
    padding = 8
    cols = max(1, math.ceil(math.sqrt(len(map_ids))))
    rows = math.ceil(len(map_ids) / cols)

    grid_img = Image.new(
        "RGB",
        (grid_w * cols + padding * (cols - 1), grid_h * rows + padding * (rows - 1)),
        (255, 255, 255),
    )
    draw = ImageDraw.Draw(grid_img)

    for idx, map_id in enumerate(map_ids):
        row = idx // cols
        col = idx % cols
        x = col * (grid_w + padding)
        y = row * (grid_h + padding)

        image_rel = run_map.get(run_id, {}).get(map_id)
        if image_rel:
            img_path = base_dir / image_rel
            tile = Image.open(img_path)
            grid_img.paste(tile, (x, y))
        else:
            draw.rectangle((x, y, x + grid_w, y + grid_h), fill=(235, 235, 235))
            _draw_label(draw, "missing", (x + 6, y + 6))

        _draw_label(draw, map_id, (x + 6, y + 26))

    _draw_label(draw, run_id, (6, 6))
    return grid_img


def _stack_grids(
    run_ids: list[str],
    run_map: dict[str, dict[str, str]],
    base_dir: Path,
    out_path: Path,
    map_ids: list[str],
) -> Path:
    grids = [_build_run_grid(run_id, run_map, base_dir, map_ids) for run_id in run_ids]
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


def _summarize_runs(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["run_id"], []).append(row)

    summary: dict[str, dict[str, float]] = {}
    for run_id, run_rows in grouped.items():
        totals = [r["total_count"] for r in run_rows]
        drs = [r["dr_count"] for r in run_rows]
        total_mean = statistics.mean(totals)
        dr_mean = statistics.mean(drs)
        ratio = dr_mean / total_mean if total_mean else 0.0
        summary[run_id] = {
            "total_count_mean": round(total_mean, 2),
            "dr_count_mean": round(dr_mean, 2),
            "dr_ratio": round(ratio, 3),
        }
    return summary


def _build_payload(rows: list[dict[str, Any]], run_summary: dict[str, dict[str, float]]) -> dict[str, Any]:
    return {
        "spec": {"total_count": SPEC_TOTAL, "dr_count": SPEC_DR},
        "run_summary": run_summary,
        "map_rows": rows,
        "units": {"count": "ea"},
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
        "너는 반도체 defect 판정 에이전트다. "
        "이미지와 데이터의 패턴/경향을 비교해서 PASS/FAIL을 판단한다. "
        "유사 패턴/경향이 있으면 PASS, 없으면 FAIL. "
        "반드시 JSON만 출력하라."
        "엔니지어 노트를 절대적으로 반영해라."
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
        "너는 반도체 defect 최종 판정 에이전트다. "
        "수평/수직 비교 결과와 이미지, 데이터까지 종합해 최종 PASS/FAIL을 판단한다. "
        "유사 패턴/경향이 하나라도 명확하면 PASS 가능. "
        "근거가 부족하면 FAIL. "
        "반드시 JSON만 출력하라."
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


def _heuristic_judge(run_summary: dict[str, dict[str, float]], current: str, compare_ids: list[str]) -> dict[str, str]:
    def vector(stats: dict[str, float]) -> list[float]:
        return [stats["total_count_mean"], stats["dr_count_mean"], stats["dr_ratio"] * 100.0]

    current_vec = vector(run_summary[current])
    best_distance = None
    best_id = None
    for run_id in compare_ids:
        other_vec = vector(run_summary[run_id])
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(current_vec, other_vec)))
        if best_distance is None or dist < best_distance:
            best_distance = dist
            best_id = run_id

    status = "PASS" if best_distance is not None and best_distance <= 18.0 else "FAIL"
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
    engineer_notes: str,
    method: str,
) -> None:
    lines = [
        "# Defect Judgement Report",
        "",
        "## Spec",
        f"- total_count <= {SPEC_TOTAL}",
        f"- dr_count <= {SPEC_DR}",
        "",
        "## Outputs",
        "- composite_horizontal.png",
        "- composite_vertical.png",
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
        "## Run Summary (mean per run)",
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

    run_profiles = {
        "current_run": {"total": 105, "dr": 50, "pattern": "ring", "total_sigma": 0.06, "dr_sigma": 0.06},
        "peer_tool_1": {"total": 90, "dr": 40, "pattern": "ring", "total_sigma": 0.14, "dr_sigma": 0.16},
        "peer_tool_2": {"total": 75, "dr": 30, "pattern": "edge", "total_sigma": 0.2, "dr_sigma": 0.22},
        "peer_tool_3": {"total": 125, "dr": 62, "pattern": "center", "total_sigma": 0.1, "dr_sigma": 0.12},
        "history_run_1": {"total": 130, "dr": 64, "pattern": "edge", "total_sigma": 0.12, "dr_sigma": 0.14},
        "history_run_2": {"total": 92, "dr": 42, "pattern": "ring", "total_sigma": 0.08, "dr_sigma": 0.1},
        "history_run_3": {"total": 88, "dr": 38, "pattern": "random", "total_sigma": 0.18, "dr_sigma": 0.2},
    }

    rows: list[dict[str, Any]] = []
    for run_id, profile in run_profiles.items():
        for map_id in MAP_IDS:
            rng = _seeded_rng(f"{run_id}-{map_id}")
            total_sigma = float(profile.get("total_sigma", 0.12))
            dr_sigma = float(profile.get("dr_sigma", 0.15))
            total = max(10, int(rng.gauss(profile["total"], profile["total"] * total_sigma)))
            dr = max(0, int(rng.gauss(profile["dr"], profile["dr"] * dr_sigma)))
            dr = min(dr, total)
            pattern = str(profile.get("pattern", "random"))
            img = _render_wafer(total, dr, rng, pattern)
            file_name = f"{run_id}_{map_id}.png"
            img.save(images_dir / file_name)

            rows.append(
                {
                    "run_id": run_id,
                    "map_id": map_id,
                    "image_file": f"images/{file_name}",
                    "total_count": total,
                    "dr_count": dr,
                }
            )

    csv_path = base_dir / "defect_data.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    notes_path = base_dir / "engineer_notes_sample.txt"
    if not notes_path.exists():
        notes_path.write_text(
            "Use PASS if pattern similarity exists across peers/history even near spec limits.\n"
            "Prioritize matching spatial trends (ring/edge/center) over raw counts.\n"
            "If no comparable trend or evidence, keep FAIL.\n",
            encoding="utf-8",
        )

    run_map = _build_run_map(rows)
    peers, history = _split_runs(list(run_profiles.keys()))
    _stack_grids(
        [RUN_CURRENT, *peers],
        run_map,
        base_dir,
        base_dir / "composite_horizontal.png",
        MAP_IDS,
    )
    _stack_grids(
        [RUN_CURRENT, *history],
        run_map,
        base_dir,
        base_dir / "composite_vertical.png",
        MAP_IDS,
    )

    run_summary = _summarize_runs(rows)
    payload = _build_payload(rows, run_summary)
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
        notes_path.read_text(encoding="utf-8"),
        "heuristic",
    )


def run_agent(
    base_dir: Path,
    data_csv: Path,
    notes_path: Path,
    model: str,
    use_llm: bool,
) -> dict[str, Any]:
    rows = _read_defect_csv(data_csv)
    run_ids = sorted({row["run_id"] for row in rows})
    map_ids = sorted({row["map_id"] for row in rows})
    if RUN_CURRENT not in run_ids:
        raise ValueError("CSV missing current_run.")
    if not map_ids:
        raise ValueError("CSV missing map_id values.")

    peers, history = _split_runs(run_ids)
    if not peers or not history:
        raise ValueError("CSV must include peer_tool_* and history_run_* runs.")

    run_summary = _summarize_runs(rows)
    payload = _build_payload(rows, run_summary)
    run_map = _build_run_map(rows)
    engineer_notes = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""

    composite_horizontal = base_dir / "composite_horizontal.png"
    composite_vertical = base_dir / "composite_vertical.png"
    _stack_grids([RUN_CURRENT, *peers], run_map, base_dir, composite_horizontal, map_ids)
    _stack_grids([RUN_CURRENT, *history], run_map, base_dir, composite_vertical, map_ids)

    if use_llm:
        horizontal_result = _llm_judge(
            composite_horizontal, payload, "horizontal", model, engineer_notes
        )
        vertical_result = _llm_judge(
            composite_vertical, payload, "vertical", model, engineer_notes
        )
        final_result = _llm_final_judge(
            composite_horizontal,
            composite_vertical,
            payload,
            horizontal_result,
            vertical_result,
            model,
            engineer_notes,
        )
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

    _write_report(
        base_dir / "report.md",
        horizontal_result,
        vertical_result,
        final_result,
        payload,
        engineer_notes,
        "llm" if use_llm else "heuristic",
    )
    return {
        "horizontal": horizontal_result,
        "vertical": vertical_result,
        "final": final_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Defect judgement agent.")
    parser.add_argument("--generate-samples", action="store_true", help="Generate sample images/data.")
    parser.add_argument("--data-csv", default="defect_data.csv", help="Path to defect data CSV.")
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

    data_csv = base_dir / args.data_csv
    notes_path = base_dir / args.engineer_notes_file
    if not data_csv.exists():
        generate_samples(base_dir)

    result = run_agent(
        base_dir=base_dir,
        data_csv=data_csv,
        notes_path=notes_path,
        model=args.model,
        use_llm=not args.no_llm,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
