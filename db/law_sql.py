"""
법령 테이블 정의와 적재 SQL (tb_law_bas / tb_law_atcl_bas / tb_law_para_bas / tb_law_*_amnd_hst)

- 임시테이블(tmp_law_*): CSV 를 그대로 받는 세션 전용 테이블 (전 컬럼 text, COMMIT 시 자동 삭제)
- 프로그램ID 는 실행 시 파라미터 %(pgm_id)s 로 전달
"""
from __future__ import annotations

from crawl.law_detail import TB_LAW_ATCL_BAS_HEADERS, TB_LAW_BAS_HEADERS, TB_LAW_PARA_BAS_HEADERS

COMMON_COLS = ['inpt_pgm_id', 'inpt_dt', 'chg_pgm_id', 'chg_dt']
CSV_ONLY_COLS = ['amnd_ymd', 'amnd_typ_nm']     # CSV 에만 있고 bas 에는 없음 (이력 기록용)

# 기본 테이블 정의: 임시테이블명, CSV 컬럼, PK, 정수 컬럼, 필수(NOT NULL) 컬럼
BAS_TABLES = {
    'tb_law_bas': {
        'tmp': 'tmp_law_bas',
        'csv_cols': [c.lower() for c in TB_LAW_BAS_HEADERS],
        'pk': ['law_enfc_id'],
        'int_cols': ['law_seq', 'prmlgt_no'],
        'nn_cols': ['law_enfc_id', 'law_seq', 'enfc_ymd', 'law_id'],
    },
    'tb_law_atcl_bas': {
        'tmp': 'tmp_law_atcl',
        'csv_cols': [c.lower() for c in TB_LAW_ATCL_BAS_HEADERS],
        'pk': ['law_enfc_id', 'law_brch_no'],
        'int_cols': ['law_seq', 'atcl_no'],
        'nn_cols': ['law_enfc_id', 'law_brch_no', 'law_seq', 'enfc_ymd', 'law_id', 'atcl_no'],
    },
    'tb_law_para_bas': {
        'tmp': 'tmp_law_para',
        'csv_cols': [c.lower() for c in TB_LAW_PARA_BAS_HEADERS],
        'pk': ['law_enfc_id', 'law_brch_no', 'para_no'],
        'int_cols': ['law_seq', 'atcl_no', 'para_no'],
        'nn_cols': ['law_enfc_id', 'law_brch_no', 'para_no', 'law_seq', 'enfc_ymd', 'law_id', 'atcl_no'],
    },
}

HST_ATCL_COLS = ['law_atcl_hsid', 'law_enfc_id', 'law_brch_no', 'law_id', 'prev_law_enfc_id', 'prev_law_brch_no',
                 'law_seq', 'prev_law_seq', 'enfc_ymd', 'prev_enfc_ymd', 'amnd_ymd', 'amnd_typ_nm',
                 'amnd_rsn_cd_nm', 'detected_dt']
HST_PARA_COLS = ['law_para_hsid', 'law_enfc_id', 'law_brch_no', 'para_no', 'law_id', 'prev_law_enfc_id',
                 'prev_law_brch_no', 'prev_para_no', 'law_seq', 'prev_law_seq', 'enfc_ymd', 'prev_enfc_ymd',
                 'amnd_ymd', 'amnd_typ_nm', 'amnd_rsn_cd_nm', 'detected_dt']


def expected_columns() -> dict:
    """precheck 용: 테이블별 필수 컬럼"""
    exp = {}
    for table, t in BAS_TABLES.items():
        exp[table] = [c for c in t['csv_cols'] if c not in CSV_ONLY_COLS] + COMMON_COLS
    exp['tb_law_atcl_amnd_hst'] = HST_ATCL_COLS + COMMON_COLS
    exp['tb_law_para_amnd_hst'] = HST_PARA_COLS + COMMON_COLS
    return exp


# ── 이력 PK 해시 ────────────────────────────────────────────────────────────
# !! 운영 적재 시작 후 변경 금지: 재료 순서·구분자('|')·NULL→'' 처리를 바꾸면 이력이 중복으로 쌓임
#    조: law_id|law_brch_no|law_enfc_id|prev_law_enfc_id|amnd_rsn_cd_nm|atcl_ctxt_hsid
#    항: law_id|law_brch_no|para_no|law_enfc_id|prev_law_enfc_id|amnd_rsn_cd_nm|para_ctxt_hsid
def _hsid(*exprs) -> str:
    parts = ", ".join(f"COALESCE(({e})::text, '')" for e in exprs)
    return f"encode(sha256(convert_to(concat_ws('|', {parts}), 'UTF8')), 'hex')"


def _cast(col: str, int_cols: list, alias: str = 's') -> str:
    if col in int_cols:   # 숫자가 아니면 NULL (필수 정수 컬럼은 delete_invalid_sql 에서 미리 걸러짐)
        return f"CASE WHEN {alias}.{col} ~ '^[0-9]+$' THEN {alias}.{col}::int4 END"
    return f"NULLIF({alias}.{col}, '')"


# ── 기본 테이블 ─────────────────────────────────────────────────────────────
def create_tmp_sql(table: str) -> str:
    t = BAS_TABLES[table]
    cols = ', '.join(f'{c} text' for c in t['csv_cols'])
    return f"CREATE TEMP TABLE {t['tmp']} ({cols}) ON COMMIT DROP"


def copy_sql(table: str) -> str:
    t = BAS_TABLES[table]
    return f"COPY {t['tmp']} ({', '.join(t['csv_cols'])}) FROM STDIN WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')"


def delete_invalid_sql(table: str) -> str:
    """키/필수값이 비었거나 필수 정수 컬럼이 숫자가 아닌 행 제거 (1건 때문에 전체 롤백되는 것 방지)"""
    t = BAS_TABLES[table]
    conds = []
    for c in t['nn_cols']:
        if c in t['int_cols']:
            conds.append(f"COALESCE({c}, '') !~ '^[0-9]+$'")
        else:
            conds.append(f"COALESCE({c}, '') = ''")
    return f"DELETE FROM {t['tmp']} WHERE {' OR '.join(conds)}"


def count_new_sql(table: str) -> str:
    t = BAS_TABLES[table]
    on = ' AND '.join(f'b.{c} = {_cast(c, t["int_cols"])}' for c in t['pk'])
    return f"SELECT count(*) FROM {t['tmp']} s WHERE NOT EXISTS (SELECT 1 FROM {table} b WHERE {on})"


def upsert_sql(table: str) -> str:
    """신규 INSERT / 기존 행은 값이 달라진 경우에만 UPDATE (chg_dt, chg_pgm_id 갱신)"""
    t = BAS_TABLES[table]
    cols = [c for c in t['csv_cols'] if c not in CSV_ONLY_COLS]
    non_pk = [c for c in cols if c not in t['pk']]
    exprs = ', '.join(_cast(c, t['int_cols']) for c in cols)
    set_clause = ',\n    '.join(f'{c} = EXCLUDED.{c}' for c in non_pk)
    old_row = ', '.join(f'{table}.{c}' for c in non_pk)
    new_row = ', '.join(f'EXCLUDED.{c}' for c in non_pk)
    return f"""
INSERT INTO {table} ({', '.join(cols)}, inpt_pgm_id, chg_pgm_id)
SELECT {exprs}, %(pgm_id)s, %(pgm_id)s
FROM {t['tmp']} s
ON CONFLICT ({', '.join(t['pk'])}) DO UPDATE SET
    {set_clause},
    chg_pgm_id = EXCLUDED.chg_pgm_id,
    chg_dt     = now()
WHERE ({old_row}) IS DISTINCT FROM ({new_row})
"""


# ── anomaly: 같은 PK 인데 이번 수집 본문해시가 DB 저장값과 다름 (bas 갱신 전에 실행) ──
ANOMALY_ATCL_SQL = f"""
INSERT INTO tb_law_atcl_amnd_hst ({', '.join(HST_ATCL_COLS)}, inpt_pgm_id, chg_pgm_id)
SELECT {_hsid('t.law_id', 't.law_brch_no', 't.law_enfc_id', 't.law_enfc_id', "'anomaly'", 's.atcl_ctxt_hsid')},
       t.law_enfc_id, t.law_brch_no, t.law_id, t.law_enfc_id, t.law_brch_no,
       s.law_seq::int4, t.law_seq, s.enfc_ymd, t.enfc_ymd,
       NULLIF(s.amnd_ymd, ''), NULLIF(s.amnd_typ_nm, ''), 'anomaly', now(),
       %(pgm_id)s, %(pgm_id)s
FROM tmp_law_atcl s
JOIN tb_law_atcl_bas t ON t.law_enfc_id = s.law_enfc_id AND t.law_brch_no = s.law_brch_no
WHERE t.atcl_ctxt_hsid IS DISTINCT FROM s.atcl_ctxt_hsid
ON CONFLICT (law_atcl_hsid) DO NOTHING
"""

ANOMALY_PARA_SQL = f"""
INSERT INTO tb_law_para_amnd_hst ({', '.join(HST_PARA_COLS)}, inpt_pgm_id, chg_pgm_id)
SELECT {_hsid('t.law_id', 't.law_brch_no', 't.para_no', 't.law_enfc_id', 't.law_enfc_id', "'anomaly'", 's.para_ctxt_hsid')},
       t.law_enfc_id, t.law_brch_no, t.para_no, t.law_id, t.law_enfc_id, t.law_brch_no, t.para_no::text,
       s.law_seq::int4, t.law_seq, s.enfc_ymd, t.enfc_ymd,
       NULLIF(s.amnd_ymd, ''), NULLIF(s.amnd_typ_nm, ''), 'anomaly', now(),
       %(pgm_id)s, %(pgm_id)s
FROM tmp_law_para s
JOIN tb_law_para_bas t ON t.law_enfc_id = s.law_enfc_id AND t.law_brch_no = s.law_brch_no
                      AND t.para_no = s.para_no::int4
WHERE t.para_ctxt_hsid IS DISTINCT FROM s.para_ctxt_hsid
ON CONFLICT (law_para_hsid) DO NOTHING
"""

# ── amendment: 같은 조(항)의 인접 연혁끼리 본문해시가 다름 (bas 갱신 후, bas 전체 기준) ──
# 연혁 정렬: 색인쿼리 LEAD 와 같은 순서 + 마지막에 law_seq (동순위여도 매 실행 같은 순서 → 멱등)
AMENDMENT_ATCL_SQL = f"""
WITH o AS (
    SELECT a.law_enfc_id, a.law_brch_no, a.law_id, a.law_seq, a.enfc_ymd, a.atcl_ctxt_hsid,
           LAG(a.law_enfc_id)    OVER w AS prev_law_enfc_id,
           LAG(a.law_seq)        OVER w AS prev_law_seq,
           LAG(a.enfc_ymd)       OVER w AS prev_enfc_ymd,
           LAG(a.atcl_ctxt_hsid) OVER w AS prev_hsid
    FROM tb_law_atcl_bas a
    JOIN tb_law_bas b ON b.law_enfc_id = a.law_enfc_id
    WINDOW w AS (PARTITION BY a.law_id, a.law_brch_no
                 ORDER BY a.enfc_ymd, b.prmlgt_no, b.entrvs_dvs_cd, a.law_seq)
)
INSERT INTO tb_law_atcl_amnd_hst ({', '.join(HST_ATCL_COLS)}, inpt_pgm_id, chg_pgm_id)
SELECT {_hsid('o.law_id', 'o.law_brch_no', 'o.law_enfc_id', 'o.prev_law_enfc_id', "'amendment'", 'o.atcl_ctxt_hsid')},
       o.law_enfc_id, o.law_brch_no, o.law_id, o.prev_law_enfc_id, o.law_brch_no,
       o.law_seq, o.prev_law_seq, o.enfc_ymd, o.prev_enfc_ymd,
       NULLIF(s.amnd_ymd, ''), NULLIF(s.amnd_typ_nm, ''), 'amendment', now(),
       %(pgm_id)s, %(pgm_id)s
FROM o
LEFT JOIN tmp_law_atcl s ON s.law_enfc_id = o.law_enfc_id AND s.law_brch_no = o.law_brch_no
WHERE o.prev_law_enfc_id IS NOT NULL
  AND o.atcl_ctxt_hsid IS DISTINCT FROM o.prev_hsid
ON CONFLICT (law_atcl_hsid) DO NOTHING
"""

AMENDMENT_PARA_SQL = f"""
WITH o AS (
    SELECT p.law_enfc_id, p.law_brch_no, p.para_no, p.law_id, p.law_seq, p.enfc_ymd, p.para_ctxt_hsid,
           LAG(p.law_enfc_id)    OVER w AS prev_law_enfc_id,
           LAG(p.law_seq)        OVER w AS prev_law_seq,
           LAG(p.enfc_ymd)       OVER w AS prev_enfc_ymd,
           LAG(p.para_ctxt_hsid) OVER w AS prev_hsid
    FROM tb_law_para_bas p
    JOIN tb_law_bas b ON b.law_enfc_id = p.law_enfc_id
    WINDOW w AS (PARTITION BY p.law_id, p.law_brch_no, p.para_no
                 ORDER BY p.enfc_ymd, b.prmlgt_no, b.entrvs_dvs_cd, p.law_seq)
)
INSERT INTO tb_law_para_amnd_hst ({', '.join(HST_PARA_COLS)}, inpt_pgm_id, chg_pgm_id)
SELECT {_hsid('o.law_id', 'o.law_brch_no', 'o.para_no', 'o.law_enfc_id', 'o.prev_law_enfc_id', "'amendment'", 'o.para_ctxt_hsid')},
       o.law_enfc_id, o.law_brch_no, o.para_no, o.law_id, o.prev_law_enfc_id, o.law_brch_no, o.para_no::text,
       o.law_seq, o.prev_law_seq, o.enfc_ymd, o.prev_enfc_ymd,
       NULLIF(s.amnd_ymd, ''), NULLIF(s.amnd_typ_nm, ''), 'amendment', now(),
       %(pgm_id)s, %(pgm_id)s
FROM o
LEFT JOIN tmp_law_para s ON s.law_enfc_id = o.law_enfc_id AND s.law_brch_no = o.law_brch_no
                        AND s.para_no = o.para_no::text
WHERE o.prev_law_enfc_id IS NOT NULL
  AND o.para_ctxt_hsid IS DISTINCT FROM o.prev_hsid
ON CONFLICT (law_para_hsid) DO NOTHING
"""

# ── 조회 ────────────────────────────────────────────────────────────────────
# 이번 트랜잭션에서 새로 들어간 이력 (같은 트랜잭션 안에서는 now() 가 고정 → detected_dt = now())
HST_LOG_SQL = """
SELECT h.amnd_rsn_cd_nm, h.law_id, b.law_kor_nm, h.law_brch_no, '' AS para_no,
       h.prev_law_enfc_id, h.law_enfc_id, h.prev_enfc_ymd, h.enfc_ymd, h.amnd_ymd, h.amnd_typ_nm
FROM tb_law_atcl_amnd_hst h LEFT JOIN tb_law_bas b ON b.law_enfc_id = h.law_enfc_id
WHERE h.detected_dt = now()
UNION ALL
SELECT h.amnd_rsn_cd_nm, h.law_id, b.law_kor_nm, h.law_brch_no, h.para_no::text,
       h.prev_law_enfc_id, h.law_enfc_id, h.prev_enfc_ymd, h.enfc_ymd, h.amnd_ymd, h.amnd_typ_nm
FROM tb_law_para_amnd_hst h LEFT JOIN tb_law_bas b ON b.law_enfc_id = h.law_enfc_id
WHERE h.detected_dt = now()
ORDER BY 1, 2, 4, 5, 9
"""
HST_LOG_HEADER = ['구분', '법령ID', '법령명', '조(가지번호)', '항', '직전연혁ID', '이번연혁ID',
                  '직전시행일', '이번시행일', '개정일', '개정유형']

SUMMARY_SQL = """
SELECT 'tb_law_bas', count(*) FROM tb_law_bas
UNION ALL SELECT 'tb_law_atcl_bas', count(*) FROM tb_law_atcl_bas
UNION ALL SELECT 'tb_law_para_bas', count(*) FROM tb_law_para_bas
UNION ALL SELECT 'tb_law_atcl_amnd_hst(' || amnd_rsn_cd_nm || ')', count(*) FROM tb_law_atcl_amnd_hst GROUP BY amnd_rsn_cd_nm
UNION ALL SELECT 'tb_law_para_amnd_hst(' || amnd_rsn_cd_nm || ')', count(*) FROM tb_law_para_amnd_hst GROUP BY amnd_rsn_cd_nm
"""
