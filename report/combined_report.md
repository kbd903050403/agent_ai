# Combined Report

## Overall Status
- Status: FAIL
- Reason: 종합 판단: FAIL. 근거: Inline 측정에서 thickness mean/min/max(742.32 / 741.80 / 742.90um)가 spec_max(740.0um)를 초과하여 명확한 spec-out이 발생하였습니다. Inline 에이전트는 편차 비율은 허용 범위(±5%) 내이나, 엔지니어 노트·개발자 지침상 vertical_match 및 horizontal_match가 모두 false이고 peer/history에서 동일 방향의 drift 또는 반복된 spec-out 근거가 부족하여 spec-out을 무시할 수 없다고 판단하였습니다. Defect와 FDC는 peer/history와의 패턴·트렌드 일치로 PASS 판단을 제시하였으나(결함 공간적 패턴 및 param_pressure drift 근거 충분), 이는 물리적 두께가 spec을 초과한 사실을 상쇄할 만큼 강한 근거가 아니므로 최종 판정은 FAIL로 유지합니다.
- Method: llm

## Inline
- Status: FAIL
- Reason: thickness mean/min/max가 spec_max(740.0um)를 초과(현재 742.32 / 741.80 / 742.90um)하나, spec 평균(=(730+740)/2=735um) 대비 편차는 각각 약 0.99% / 0.93% / 1.08%로 엔지니어 노트의 ±5% 기준은 만족함. 그러나 엔지니어 노트와 개발자 지침에 따라 수직(이전 history)·수평(peer) 비교가 일치해야 PASS 고려 가능함. 현재 vertical_match 및 horizontal_match 모두 false이며, peer tool 평균(≈734.84, 735.33um)과 history 평균(≈734.8–735.3um)은 상기 방향(상승)으로 drift를 보이지 않음. 또한 이전 history에서 동일한 spec-out 반복도 확인되지 않음. 근거(동일 방향의 peer drift 또는 반복된 history spec-out)가 부족하므로 FAIL 유지 판단함.
- Data: `/Volumes/X31/DSP_agent/inline/sample_inline_fail.csv`
- Spec: `/Volumes/X31/DSP_agent/inline/sample_spec.csv`
- Spec-out:
  - thickness mean above spec_max (740.000 um); current 742.320 um; vertical match: no; horizontal match: no
  - thickness min above spec_max (740.000 um); current 741.800 um; vertical match: no; horizontal match: no
  - thickness max above spec_max (740.000 um); current 742.900 um; vertical match: no; horizontal match: no

## Defect
- Status: PASS
- Reason: 판정 근거: 현재 런의 4개 맵(map_1~map_4)에서 결함이 일관되게 링(외곽/중간 반경) 형태로 분포하여 명확한 공간적 트렌드가 관찰됩니다. peer_tool_1, peer_tool_2 및 history_run_1, history_run_2에서도 유사한 링/엣지 분포가 반복적으로 확인되어 다수의 peer/이력과 공간적 경향이 일치합니다(단, peer_tool_3는 중앙집중형 분포를 보이나 다수의 비교 대상은 링 트렌드를 따름). 수치적 근거로 현재 런의 총카운트 평균은 109.75 ea로 사양(total_count 100)을 소폭 초과하나, DR 비율은 0.44로 사양 DR(50→0.50) 대비 근접하며 peers/history 범위(대략 0.356–0.531) 내에 있습니다. 엔지니어 노트에 따라 동일한 공간적 패턴/유사 경향이 확인될 경우 패턴 유사성을 우선 적용하므로, 전반적 근거가 충분하여 PASS 판정합니다.
- Data: `/Volumes/X31/DSP_agent/defect/defect_data.csv`
- Spec: total_count <= 100, dr_count <= 50

### Defect Composites
![defect horizontal](/Volumes/X31/DSP_agent/defect/composite_horizontal.png)
![defect vertical](/Volumes/X31/DSP_agent/defect/composite_vertical.png)

### Flagged Maps (current_run)
- map_1: total=112.0, dr=50.0 (`/Volumes/X31/DSP_agent/defect/images/current_run_map_1.png`)
![map_1](/Volumes/X31/DSP_agent/defect/images/current_run_map_1.png)
- map_2: total=105.0, dr=49.0 (`/Volumes/X31/DSP_agent/defect/images/current_run_map_2.png`)
![map_2](/Volumes/X31/DSP_agent/defect/images/current_run_map_2.png)
- map_3: total=113.0, dr=45.0 (`/Volumes/X31/DSP_agent/defect/images/current_run_map_3.png`)
![map_3](/Volumes/X31/DSP_agent/defect/images/current_run_map_3.png)
- map_4: total=109.0, dr=49.0 (`/Volumes/X31/DSP_agent/defect/images/current_run_map_4.png`)
![map_4](/Volumes/X31/DSP_agent/defect/images/current_run_map_4.png)

## FDC
- Status: PASS
- Reason: 엔지니어 노트 기준에 따라 판단함. fail 파라미터 param_pressure의 step 7에서 현재 런은 평균이 기준 대비 +5.604로 뚜렷한 상승(단계 중심의 plateau/peak)과 약한 양의 기울기(0.000903)를 보임. 동일 step에서 peer_tool_1(delta=+4.491, slope=0.00064, std≈0.255)과 history_run_2(delta=+5.111, slope=0.000552, std≈0.251)도 유사한 크기와 방향의 양(positive) 이동 및 단계 중심 피크/플레토 형태를 보여 trend shape(증가·플레토)과 노이즈 수준이 일치함. 일부 peer/history는 변화가 작으나 복수의 peer/history에서 현재와 유사한 드리프트/피크 패턴이 관찰되어 근거가 충분하므로 PASS 판정함.
- Fail: param_pressure / step 7
- Data: `/Volumes/X31/DSP_agent/fdc/timeseries.csv`
- Images: `/Volumes/X31/DSP_agent/fdc/trend_images.csv`

### FDC Composites
![fdc horizontal](/Volumes/X31/DSP_agent/fdc/composite_horizontal.png)
![fdc vertical](/Volumes/X31/DSP_agent/fdc/composite_vertical.png)

## Highlights
- Inline: spec-out metrics listed above (if any).
- Defect: flagged current_run maps listed and composite images shown.
- FDC: fail parameter/step focus with composite images.