# Inline Judgement Report

## Inputs
- csv: `/Volumes/X31/DSP_agent/inline/sample_inline_fail.csv`
- spec: `/Volumes/X31/DSP_agent/inline/sample_spec.csv`
- engineer_notes: `/Volumes/X31/DSP_agent/inline/engineer_notes_sample.txt`
- alignment_tolerance: 0.0

## Spec Limits
- thickness: 730.0 ~ 740.0
- range: 0.0 ~ 2.0
- edge_thk: 730.0 ~ 740.0
- edge_range: 0.0 ~ 2.2

## Spec-Out
- thickness mean above spec_max (740.000 um); current 742.320 um; vertical match: no; horizontal match: no
- thickness min above spec_max (740.000 um); current 741.800 um; vertical match: no; horizontal match: no
- thickness max above spec_max (740.000 um); current 742.900 um; vertical match: no; horizontal match: no

## Spec-Out Alignment
- thickness mean: current=742.32, spec=[730.0, 740.0], vertical_match=False, horizontal_match=False
- thickness min: current=741.8, spec=[730.0, 740.0], vertical_match=False, horizontal_match=False
- thickness max: current=742.9, spec=[730.0, 740.0], vertical_match=False, horizontal_match=False

## Final Decision
- Status: FAIL
- Reason: thickness mean/min/max가 spec_max(740.0um)를 초과(현재 742.32 / 741.80 / 742.90um)하나, spec 평균(=(730+740)/2=735um) 대비 편차는 각각 약 0.99% / 0.93% / 1.08%로 엔지니어 노트의 ±5% 기준은 만족함. 그러나 엔지니어 노트와 개발자 지침에 따라 수직(이전 history)·수평(peer) 비교가 일치해야 PASS 고려 가능함. 현재 vertical_match 및 horizontal_match 모두 false이며, peer tool 평균(≈734.84, 735.33um)과 history 평균(≈734.8–735.3um)은 상기 방향(상승)으로 drift를 보이지 않음. 또한 이전 history에서 동일한 spec-out 반복도 확인되지 않음. 근거(동일 방향의 peer drift 또는 반복된 history spec-out)가 부족하므로 FAIL 유지 판단함.
- Method: llm