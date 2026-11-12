# 결과 보는 방법

## 가장 쉬운 순서

1. GitHub의 [`results/minimal/README.md`](../results/minimal/README.md)를 열어 요약과 그래프를 확인합니다.
2. [`results.xlsx`](../results/minimal/results.xlsx)를 **Download raw file**로 내려받아 Excel에서 엽니다. `summary` 시트의 수치와 차량 상태 차트를 먼저 보고, `passengers`에서 요청별 기록을 확인합니다.
3. [`simulation.gif`](../results/minimal/simulation.gif)에서 차량 움직임을 봅니다. 노랑은 픽업 이동, 빨강은 서비스 중, 초록은 유휴, 보라색은 구역 간 이동입니다. 검은 테두리가 있는 차량은 그 프레임에 2명이 탑승한 상태입니다. 최소 예제에서는 구역 간 이동이 없습니다.
4. 연구 분석에는 CSV 또는 SQLite를 사용합니다. 그림만으로 서비스 수준을 평가하지 마십시오.

## 파일과 시트

| 파일 / Excel 시트 | 한 행의 의미 | 핵심 열 |
|---|---|---|
| `summary.json` / `summary` | 지표 | 생성·배정·완료·거절·미완료, 완료 승객 대기·차내·총시간 |
| `config.json` / `config` | 설정값 | 실행에 사용한 JSON 설정의 기록 |
| `requests.csv` / `requests` | 실제 입력 요청 1개 | 요청 ID, 요청시각, origin/destination |
| `fleet_timeseries.csv` / 동일 시트 | 1개 시간 스텝 | assigned, in_service, idle, inter, arrivals_cumulative |
| `passengers.csv` / `passengers` | 승객 요청 1개 | 배차·픽업·하차시각, 최종 상태, wait/ride/total_min |
| `vehicles.csv` / `vehicles` | 차량 1대 | 상태별 누적 시간과 실제 이동거리, 종료 위치 |
| `trajectories.csv` / `trajectories` | 기록 시각의 차량 1대 | 좌표, 상태, registered_load, onboard |
| `simulation.sqlite` | 위 자료를 모은 DB | 위 표 이름과 summary, config 테이블 |
| `run_metadata.json` | 실행 1회 | 원본 커밋, Python·패키지 버전, 실행 코드·설정 해시 |

CSV 인코딩은 UTF-8 BOM으로 Windows Excel에서 열기 쉽게 저장합니다. Excel의 수치들은 시뮬레이션 관측값입니다. 설정 셀을 고쳐도 다시 계산되는 모델이 아니며 JSON 설정을 바꾼 뒤 Python을 재실행해야 합니다.

## 단위와 정의

- 시간 열의 `_h`는 시간(hour), `_min`은 분, 설정의 `_seconds`는 초입니다.
- 좌표와 거리 단위는 mile, 속도는 mile/hour입니다.
- `wait_min = (pickup_time_h - request_time_h) × 60`.
- `ride_min = (dropoff_time_h - pickup_time_h) × 60`.
- `total_min = wait_min + ride_min`. 완료하지 않은 경우 총시간은 빈 값입니다.
- `assigned_to_busy_vehicle`는 이미 서비스 중인 차량에 새로 추가 배정된 요청입니다.
- `experienced_shared_ride`는 실제로 다른 승객과 동시에 탑승했던 승객입니다. 먼저 탑승한 승객도 True가 될 수 있습니다.
- `registered_load`는 픽업 전 등록 승객을 포함합니다. `onboard`가 실제 탑승 인원입니다.
- `initial_assignments`는 유휴차량에 대한 최초 배차 횟수입니다. 합승 추가나 실제 완료 승객 수와 다릅니다.
- `arrivals_cumulative`는 해당 시각까지 실제 발생한 고유 요청 수입니다. `processed_unique_cumulative`는 배차 루프에서 한 번 이상 처리한 고유 요청 수이며 batch에서는 배차 경계 사이에 두 값이 다를 수 있습니다.
- 상태 시계열은 각 스텝의 요청 처리·이동 전 상태입니다. 궤적은 기록 시점의 요청 처리 후·이동 전 상태를 담고 마지막 T의 스냅샷도 추가합니다.

승객 최종 상태: `waiting_assignment`(0), `waiting_pickup`(1), `onboard`(2), `completed`(3), `rejected`(-1).

`completed_mean_*`는 완료한 승객만의 평균입니다. 종료 시 미완료 승객을 제외하므로 종료 시점의 절단 편향이 있습니다. 완료율·거절률·미완료 수를 함께 보십시오. 관측치가 없으면 평균을 0으로 채우지 않고 빈 값/JSON null로 둡니다.

## Python으로 CSV 확인

```python
import pandas as pd

p = pd.read_csv("results/minimal/passengers.csv")
print(p["status"].value_counts())
completed = p[p["status"] == "completed"]
print(completed[["wait_min", "ride_min", "total_min"]].describe())
```

## SQLite DB 조회

무료 SQLite GUI나 Python의 기본 `sqlite3` 모듈로 조회할 수 있습니다. 별도 DB 서버는 필요 없습니다.

```python
import sqlite3
import pandas as pd

with sqlite3.connect("results/minimal/simulation.sqlite") as con:
    print(pd.read_sql_query("SELECT status, COUNT(*) AS n FROM passengers GROUP BY status", con))
    print(pd.read_sql_query("SELECT AVG(wait_min) AS mean_wait_min FROM passengers WHERE status='completed'", con))
```

입력 도로망 DB는 `data/processed/network.sqlite`입니다. `nodes(node_id,x_coord,y_coord)`, `links(link_id,from_node_id,to_node_id)`, `metadata(key,value)`로 구성됩니다. 노드·링크 ID는 기본키이고 링크의 끝점은 노드에 대한 외래키입니다. 최소 Manhattan 실행 결과 DB와는 용도가 다릅니다. 실도로 입력은 12개의 약연결 성분으로 나뉘며 최소 예제에 사용되지 않습니다.

## 결과 재현

같은 config와 패키지 버전으로 `python run_simulation.py`를 실행하십시오. 입력 requests.csv, 승객 결과, 요약 수치를 비교하면 됩니다. GIF 인코딩, Excel 메타데이터, 생성시각 때문에 파일 바이트 해시가 항상 같지는 않습니다. 원본 대비 버그 수정과 수요/차량 RNG 분리로 이전 원본 검사 수치와는 달라질 수 있습니다.
