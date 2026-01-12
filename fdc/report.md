# FDC Judgement Report

## Inputs
- composite_horizontal.png
- composite_vertical.png
- timeseries.csv
- trend_images.csv
- taq_fail.csv

## Fail Focus
- parameter: param_pressure
- step_no: 7

## Engineer Notes
PASS 가능 기준: 동일 step에서 유사한 드리프트/피크/노이즈 패턴이 peer/history에 존재.
Fail step 중심으로 trend shape(증가/감소/oscillation)를 우선 비교.
근거 부족하거나 방향성 불일치 시 FAIL 유지

## Horizontal Comparison (current vs peers)
- Status: PASS
- Reason: param_pressure 7단계에서 현재 런은 기준 대비 평균이 +5.604로 유의한 상승을 보임. 동일 단계의 peer_tool_1(+4.491) 및 history_run_2(+5.111)에서도 유사한 양의 편차(Δ ≈4.49–5.11)와 유사한 표준편차(약 0.25–0.27), 완만한 양의 기울기(0.0005–0.0009)를 보여 동일한 상승(plateau/shift) 패턴이 관찰됨. 일부 peer/history는 변화가 작지만, 동등한 방향성과 크기의 변동을 보이는 동료/이력 사례가 존재하므로 PASS 판단함.

## Vertical Comparison (current vs history)
- Status: PASS
- Reason: fail 파라미터 param_pressure의 step 7에서 현재 런은 평균 증가(delta=+5.604)와 약한 양의 기울기(0.000903), 그리고 단계 중심의 뚜렷한 상승(plateau/피크) 패턴을 보임. 동일 step에서 peer_tool_1(delta=+4.491, slope=0.00064)과 history_run_2(delta=+5.111, slope=0.000552)에서 유사한 크기의 양(positive) 이동 및 단계 중심 피크/플레토 형태가 관찰되어 방향성과 형태가 일치함. 표준편차(≈0.25–0.27)도 유사하여 노이즈 수준 차이는 크지 않음. 일부 history/peer는 작은 변화만 보이나, 동일한 step에서 복수의 peer/history가 현재와 유사한 드리프트/피크 패턴을 보이므로 PASS 판정함.

## Final Decision
- Status: PASS
- Reason: 엔지니어 노트 기준에 따라 판단함. fail 파라미터 param_pressure의 step 7에서 현재 런은 평균이 기준 대비 +5.604로 뚜렷한 상승(단계 중심의 plateau/peak)과 약한 양의 기울기(0.000903)를 보임. 동일 step에서 peer_tool_1(delta=+4.491, slope=0.00064, std≈0.255)과 history_run_2(delta=+5.111, slope=0.000552, std≈0.251)도 유사한 크기와 방향의 양(positive) 이동 및 단계 중심 피크/플레토 형태를 보여 trend shape(증가·플레토)과 노이즈 수준이 일치함. 일부 peer/history는 변화가 작으나 복수의 peer/history에서 현재와 유사한 드리프트/피크 패턴이 관찰되어 근거가 충분하므로 PASS 판정함.
- Method: llm

## Run Summary (fail step stats)
- current_run: {'fail_mean': 53.757, 'base_mean': 48.153, 'delta': 5.604, 'fail_std': 0.273, 'fail_slope': 0.000903}
- peer_tool_1: {'fail_mean': 52.433, 'base_mean': 47.942, 'delta': 4.491, 'fail_std': 0.255, 'fail_slope': 0.00064}
- peer_tool_2: {'fail_mean': 48.811, 'base_mean': 48.751, 'delta': 0.06, 'fail_std': 0.268, 'fail_slope': 0.000913}
- history_run_1: {'fail_mean': 49.059, 'base_mean': 48.951, 'delta': 0.108, 'fail_std': 0.257, 'fail_slope': 0.000583}
- history_run_2: {'fail_mean': 53.362, 'base_mean': 48.251, 'delta': 5.111, 'fail_std': 0.251, 'fail_slope': 0.000552}
- history_run_3: {'fail_mean': 47.771, 'base_mean': 47.651, 'delta': 0.121, 'fail_std': 0.259, 'fail_slope': 0.000438}