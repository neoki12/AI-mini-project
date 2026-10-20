# 4M 도메인 데이터 — 가상 완성차 공장

국내 완성차 공장의 일반적인 공정 구조(프레스 → 차체 → 도장 → 의장)를 참고해 만든 **교육용 가상 데이터**다. 실제 회사의 표준서, 설비, 생산 데이터가 아니다.

## 구성

| 경로 | 내용 | 쓰는 곳 |
|---|---|---|
| `rules/required_items.json` | 변경 유형별 공통 필수 항목(①), 변경 등급 정의 | 권위 게이트, Validator |
| `standards/*.md` | 공장별 공정 표준과 검사 기준 9개, 조항 41개. 조건부 항목(②, `EXT-*`) 포함 | MCP Resource, RAG |
| `process_flow.json` | 공장 간 흐름과 공정 간 영향 규칙(`DS-*`) | 공정 간 영향 검토 |
| `equipment.json` | 설비 상태 스냅샷. 이상 상태 설비(③, `EXT-EQ-01`) 포함 | MCP Tool |
| `production.json` | 라인 가동 상태 스냅샷. 가동 중 라인(③, `EXT-LOT-01`) 포함 | MCP Tool |

## 정답의 세 층

| 층 | 항목 ID | 어디서 나오나 | 측정되는 효과 |
|---|---|---|---|
| ① 공통 필수 | `COM-*`, `MAN-*`, `MAC-*`, `MAT-*`, `MET-*` | 규칙표 | 권위 게이트 |
| ② 문서 근거 | `EXT-PR-01`, `EXT-BD-01`, `EXT-PT-01`, `EXT-AS-01/02` | 표준서 조건부 조항 | RAG |
| ③ 현장 데이터 | `EXT-EQ-01`, `EXT-LOT-01` | 설비·생산 Tool + QS-CM-001 조항 4, 5 | MCP Tool |
| 공정 간 영향 | `DS-*` | process_flow.json | 영향 전파 |

## 표준서 작성 규칙

- front-matter: `doc_id`, `title`, `rev`, `shop`, `doc_type`(`common-rule` / `shop-standard` / `inspection-criteria`), `change_types`
- 조항 제목은 `## 조항 {번호} {제목}` 형식을 지킨다. RAG 청크와 근거 인용(문서ID, 조항, 개정판)이 이 형식에 의존한다
- 조건부 항목은 조항 본문에 ID를 괄호로 적는다. 예: `파괴 검사를 실시한다(EXT-BD-01)`

## 데이터를 고친 뒤

```bash
python3 eval/build_4m_dataset.py     # 평가 데이터셋 재생성 (required_items는 규칙표에서 자동 계산)
python3 tests/test_4m_data.py        # 정합성 검사 10개
```
