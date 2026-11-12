# 실행 검증 기록

검증일: 2026-11-12. 기본 설정: `configs/minimal.json`.

## 실제 실행

```bash
python scripts/prepare_network.py
python run_simulation.py --config configs/minimal.json
python -m unittest discover -s tests -v
```

- 의존성 대체 모듈이나 mock 없이 설치된 실제 NumPy·SciPy·pandas·matplotlib·Pillow·xlrd·XlsxWriter로 실행했습니다.
- 기본 CLI는 사용하지 않는 PuLP/tqdm에 의존하지 않습니다. PuLP 전역 재배치는 별도 선택 설치 기능입니다.
- 11개 unittest 통과: 방향별 우회, 빈 수요·기간 경계, 배치 공급 부족 시 요청 보존, 동일 seed 재현성, 차량 수 변경 시 수요 동일성, Manhattan/Euclidean 합승 승하차 순서, 차량 보존·이벤트 시각, 다중 구역 gr=False 초기화, 미지원 도로망의 명시적 오류, 재실행 방지.
- 원본 텍스트 소스 19개의 Git blob 해시를 원본 응답과 대조했습니다. 원본 XLS 데이터의 SHA-256을 기록했습니다.
- 686노드·1,832링크의 입력 DB와 결과 DB에 대해 SQLite integrity_check를 통과했습니다. 입력 DB의 외래키 검사도 통과했습니다.
- Excel 7개 시트를 읽어 행수와 주요 요약 수치를 CSV/JSON/DB와 대조했습니다. 차량 20행, 승객 54행, 시간별 상태 3,600행, 궤적 1,220행입니다.
- PNG 3개와 GIF의 프레임을 시각 확인했습니다. GIF는 500×400, 61프레임입니다.
- 결과 메타데이터의 실행 소스 해시가 게시하는 `src/` 코드와 일치함을 확인했습니다.

## 관측 결과

| 항목 | 값 |
|---|---:|
| 생성 | 54 |
| 배정 | 54 |
| 완료 | 45 |
| 거절 | 0 |
| 미완료 | 9 (탑승 중 7, 픽업 대기 2) |
| 서비스 차량에 추가 배정 | 5 |
| 실제 동승 경험 승객 | 9 |
| 완료 승객 평균 요청~픽업 대기 | 2.770분 |
| 완료 승객 평균 차내시간 | 7.056분 |
| 완료 승객 평균 총 소요시간 | 9.826분 |

단일 난수 실행의 작동 확인 결과이며 통계적 성능평가나 현실 수요에 대한 검증은 아닙니다. T에서 종료하므로 미완료 요청을 포함한 서비스율과 완료 승객 평균을 구분합니다.

## 범위

전체 의존성의 신규 가상환경 설치, GUI, 버스, PuLP/CBC 전역 재배치, 실도로 차량 이동, 대규모 성능 및 모든 Python/OS 조합은 검증하지 않았습니다. 정확한 실행 패키지 버전과 코드 해시는 `results/minimal/run_metadata.json`을 참조하십시오.
