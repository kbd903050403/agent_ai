"""
Streamlit shell for combined report visualization.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st


def _load_report(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    st.title("Combined Agent Report")
    st.caption("Inline + Defect + FDC summary report.")

    base_dir = Path(__file__).resolve().parent
    report_path = base_dir / "combined_report.json"
    data = _load_report(report_path)

    if not data:
        st.warning("combined_report.json not found. Run: python report/agent.py")
        return

    st.subheader("Overall")
    st.write(f"Status: **{data.get('overall_status', 'UNKNOWN')}**")
    if data.get("overall_reason"):
        st.write(data.get("overall_reason"))
    if data.get("overall_method"):
        st.caption(f"Method: {data.get('overall_method')}")

    inline = data.get("inline", {})
    defect = data.get("defect", {})
    fdc = data.get("fdc", {})

    st.subheader("Inline")
    st.write(f"Status: **{inline.get('status', 'UNKNOWN')}**")
    if inline.get("reason"):
        st.write(inline.get("reason"))
    with st.expander("Inline reference data", expanded=False):
        if inline.get("spec_out_strings"):
            st.markdown("Spec-out")
            st.write("\n".join(f"- {s}" for s in inline["spec_out_strings"]))
        data_paths = inline.get("data_paths", {})
        if data_paths.get("csv"):
            st.write(f"CSV: {data_paths.get('csv')}")
        if data_paths.get("spec"):
            st.write(f"Spec: {data_paths.get('spec')}")

    st.subheader("Defect")
    st.write(f"Status: **{defect.get('status', 'UNKNOWN')}**")
    if defect.get("reason"):
        st.write(defect.get("reason"))
    with st.expander("Defect reference data", expanded=False):
        if defect.get("data_csv"):
            st.write(f"CSV: {defect.get('data_csv')}")
        if defect.get("flagged_maps"):
            st.markdown("Flagged Maps (current_run)")
            st.dataframe(defect["flagged_maps"], use_container_width=True)
            for item in defect["flagged_maps"]:
                image_path = item.get("image_path") or item.get("image_file")
                if image_path:
                    caption = f"{item.get('map_id', 'map')} (total={item.get('total_count')}, dr={item.get('dr_count')})"
                    st.image(image_path, caption=caption)
        if defect.get("composite_horizontal"):
            st.image(defect["composite_horizontal"], caption="Defect Horizontal Composite")
        if defect.get("composite_vertical"):
            st.image(defect["composite_vertical"], caption="Defect Vertical Composite")

    st.subheader("FDC")
    st.write(f"Status: **{fdc.get('status', 'UNKNOWN')}**")
    if fdc.get("reason"):
        st.write(fdc.get("reason"))
    st.write(
        f"Fail: {fdc.get('fail_parameter', '')} / step {fdc.get('fail_step_no', '')}"
    )
    with st.expander("FDC reference data", expanded=False):
        if fdc.get("timeseries_csv"):
            st.write(f"Timeseries: {fdc.get('timeseries_csv')}")
        if fdc.get("trend_images_csv"):
            st.write(f"Trend images: {fdc.get('trend_images_csv')}")
        if fdc.get("composite_horizontal"):
            st.image(fdc["composite_horizontal"], caption="FDC Horizontal Composite")
        if fdc.get("composite_vertical"):
            st.image(fdc["composite_vertical"], caption="FDC Vertical Composite")


if __name__ == "__main__":
    main()
