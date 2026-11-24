# law-collector-v2

국가법령정보 Open API(law.go.kr, XML)로 법령을 수집해 PostgreSQL에 적재한다.
조·항 단위 본문과 개정이력(amendment / anomaly)을 관리한다. (v1: law-collector-v1)

## 실행

```
cp config.yml.sample config.yml          # 환경별 값 수정
python main.py all        <env>                              # 전체: DB점검 → law_list → law_detail → load full
python main.py incr       <env> --efyd YYYYMMDD~YYYYMMDD     # 증분: 시행일자 범위의 연혁만 수집 → load incr
python main.py law_list   <env> [--efyd YYYYMMDD~YYYYMMDD]   # 법령 목록 → law_list CSV (--efyd 있으면 incr 폴더)
python main.py law_detail <env> --mode full|incr             # 법령 본문 → tb_law_* CSV (+ 수집실패 CSV)
python main.py load       <env> --mode full|incr [--ymd YYYYMMDD]   # CSV → DB (기본: 오늘 CSV)

# 백그라운드 실행 (터미널 끊겨도 계속)
nohup python3 main.py all <env> > all_$(date +%Y%m%d_%H%M).out 2>&1 &
```

### 운영 스케줄 (crontab 예시, 경로는 서버에 맞게)

일~금은 증분(전날~당일 시행분), 토요일 새벽은 전체. crontab 안에서는 `%` 를 `\%` 로 써야 한다.

```
# 일~금 23:30 증분
30 23 * * 0-5  cd /설치경로 && python3 main.py incr stg --efyd $(date -d yesterday +\%Y\%m\%d)~$(date +\%Y\%m\%d) > logs/incr_$(date +\%Y\%m\%d).out 2>&1
# 토 01:00 전체 (금→토 넘어간 새벽)
0 1 * * 6      cd /설치경로 && python3 main.py all stg > logs/all_$(date +\%Y\%m\%d).out 2>&1
```

금요일 증분이 끝나기 전에 토요일 전체가 시작되지 않도록 간격을 둔다.

- 출력: `{csv_path}/{실행일}/{full|incr}/*.csv`, 로그: `{logs_path}/{실행일}/{full|incr}/`
- 실행할 때마다 어제 이전 날짜의 CSV 폴더(full·incr 모두)는 삭제된다. 로그는 남는다.
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
| tb_law_clct_fail | law_enfc_id | 본문 수집 실패 대상 (DDL: `db/ddl/tb_law_clct_fail.sql`). 성공하면 삭제, 계속 실패하면 최종실패일자·오류만 갱신 |

공통 컬럼: inpt_pgm_id, inpt_dt, chg_pgm_id, chg_dt (프로그램ID = DB에 쓰는 파일명, 확장자 제외. 예: load_csv)

## 적재 (load_csv.py, 단일 트랜잭션)

1. CSV → 임시테이블
2. anomaly: 같은 PK인데 이번 수집 본문해시 ≠ DB 저장값 → 이력 insert (bas 변경 전)
3. bas 반영
   - full: bas 3종 TRUNCATE 후 이번 수집 성공분 insert (수집 실패한 법령은 빠짐)
   - incr: UPSERT (값이 바뀐 행만 update) + 새 현행이 들어온 법령의 이전 '현행' 행을 '연혁'으로
4. amendment: 같은 조(항)의 인접 연혁끼리 본문해시가 다르면 이력 insert
5. 수집 실패: `tb_law_clct_fail` 반영 — 해소 삭제(full = 이번에 실패하지 않은 건 전부 / incr = 이번에 성공한 건) 후 이번 실패 upsert (최초 실패 = inpt_dt, 최종 실패 = clct_ymd)
6. 이번에 새로 들어간 이력을 `{logs_path}/{ymd}/{mode}/load_hst_*.log`에 건별 기록

이력 insert는 `ON CONFLICT DO NOTHING`이라 반복 실행해도 새로 생긴 이력만 들어간다.
개정이력·수집실패 테이블은 TRUNCATE 하지 않는다. 실패 시 전체 ROLLBACK.

### 중단 조건 (DB 변경 없이 종료)

- 목록 조회 실패 (totalCnt 또는 페이지 하나라도 실패)
- 본문 연속 실패 500건 (`law_detail.MAX_CONSECUTIVE_FAIL`)

## 운영 주의

- 개정이력 테이블이 채워지는 기준은 [docs/개정이력_판별방법.md](docs/개정이력_판별방법.md) 참고.

- **해시 규칙 고정**: 본문해시(재료 구성·순서, `get_tag` 공백정리, `normalize_text`, sha256)와
  이력 PK 해시(재료 순서·`|` 구분자·NULL→'')는 운영 적재 시작 후 바꾸면 안 된다.
  바꾸면 전 조·항이 변경으로 오탐되고 이력이 중복으로 쌓인다.
- 최초 적재 시 전체 연혁의 인접 쌍이 amendment로 한꺼번에 기록된다. 이때 detected_dt는 실제 개정 시점이 아니다.
- 증분 수집으로는 anomaly가 거의 감지되지 않는다 (본문이 안 바뀐 법령은 조회되지 않음). 주 1회 전체 수집에서 감지.
- full 적재는 bas 3종을 다시 넣으므로 inpt_dt가 매주 실행 시각으로 바뀐다.
- DB timezone이 UTC면 inpt_dt / chg_dt / detected_dt가 KST와 9시간 어긋난다 (precheck가 경고).
