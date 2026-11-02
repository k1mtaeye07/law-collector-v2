# law-collector-v2

국가법령정보 Open API(law.go.kr, XML)로 법령을 수집해 PostgreSQL에 적재한다.
조·항 단위 본문과 개정이력(amendment / anomaly)을 관리한다. (v1: law-collector-v1)

## 실행

```
cp config.yml.sample config.yml          # 환경별 값 수정
python main.py law_list   <env>          # 법령 목록 → law_list CSV
python main.py law_detail <env>          # 법령 본문 → tb_law_bas / tb_law_atcl_bas / tb_law_para_bas CSV
python main.py load       <env> [--ymd YYYYMMDD]   # CSV → DB (기본: 오늘 CSV)
python main.py all        <env>          # DB점검 → law_list → law_detail → load

# 백그라운드 실행 (터미널 끊겨도 계속)
nohup python3 main.py all <env> > all_$(date +%Y%m%d_%H%M).out 2>&1 &
```

- 출력: `{csv_path}/{실행일}/*.csv`, 로그: `{logs_path}/{실행일}/`
- 필요 패키지: httpx, tenacity, tqdm, pyyaml, psycopg2 (lxml 있으면 사용)

## 구조

```
main.py              실행 진입점
crawl/law_list.py    목록 수집 (law_list CSV, 본문 수집 대상)
crawl/law_detail.py  본문 수집·파싱 (bas 3종 CSV)
load_csv.py          CSV → DB 적재 절차
db/connection.py     DB 접속, 테이블/컬럼 점검
db/law_sql.py        법령 테이블 정의, 적재·이력 판별 SQL
common/              config, 로거, CSV writer, HTTP, XML 파싱, 해시·태그 추출
```

## 테이블

| 테이블 | PK | 내용 |
|---|---|---|
| tb_law_bas | law_enfc_id | 법령 기본 (law_enfc_id = 법령일련번호+시행일자) |
| tb_law_atcl_bas | law_enfc_id, law_brch_no | 조 (law_brch_no = 조번호 4자리 + 가지번호 3자리) |
| tb_law_para_bas | law_enfc_id, law_brch_no, para_no | 항 |
| tb_law_atcl_amnd_hst | law_atcl_hsid | 조 개정이력 |
| tb_law_para_amnd_hst | law_para_hsid | 항 개정이력 |

공통 컬럼: inpt_pgm_id, inpt_dt, chg_pgm_id, chg_dt (프로그램ID = DB에 쓰는 파일명, 확장자 제외. 예: load_csv)

## 적재 (load_csv.py, 단일 트랜잭션)

1. CSV → 임시테이블
2. anomaly: 같은 PK인데 이번 수집 본문해시 ≠ DB 저장값 → 이력 insert (bas 갱신 전)
3. bas UPSERT: 신규 insert, 값이 바뀐 행만 update (삭제 없음)
4. amendment: 같은 조(항)의 인접 연혁끼리 본문해시가 다르면 이력 insert
5. 이번에 새로 들어간 이력을 `{logs_path}/{ymd}/load_hst_*.log`에 건별 기록

이력 insert는 `ON CONFLICT DO NOTHING`이라 반복 실행해도 새로 생긴 이력만 들어간다.
실패 시 전체 ROLLBACK.

## 운영 주의

- **해시 규칙 고정**: 본문해시(재료 구성·순서, `get_tag` 공백정리, `normalize_text`, sha256)와
  이력 PK 해시(재료 순서·`|` 구분자·NULL→'')는 운영 적재 시작 후 바꾸면 안 된다.
  바꾸면 전 조·항이 변경으로 오탐되고 이력이 중복으로 쌓인다.
- 최초 적재 시 전체 연혁의 인접 쌍이 amendment로 한꺼번에 기록된다. 이때 detected_dt는 실제 개정 시점이 아니다.
- 변경분만 수집하면 anomaly는 감지되지 않는다 (full 수집 필요).
- DB timezone이 UTC면 inpt_dt / chg_dt / detected_dt가 KST와 9시간 어긋난다 (precheck가 경고).
