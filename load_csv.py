"""
CSV → PostgreSQL 적재 (법령)

  python main.py load <env> --mode full|incr [--ymd YYYYMMDD]   # 이미 생성된 CSV 를 적재 (재적재 가능)

  full : 전체 수집분. bas 3종 TRUNCATE 후 이번 수집 성공분으로 다시 적재
  incr : 증분 수집분. bas 3종 UPSERT + 새 현행이 들어온 법령의 이전 '현행' 행을 '연혁'으로

단일 트랜잭션 (실패 시 전체 ROLLBACK → 기존 데이터 그대로):
  1. {csv_path}/{ymd}/tb_law_*.csv → 임시테이블 (전 컬럼 text)
  2. anomaly   : 임시테이블 vs 기존 bas 본문해시 비교 → 이력 insert   (bas 를 바꾸기 전에 해야 함)
  3. bas 반영  : full = TRUNCATE + INSERT / incr = UPSERT(값이 바뀐 행만 UPDATE) + 이전 현행 → 연혁
  4. amendment : bas 전체에서 같은 조(항) 인접 연혁 본문해시 비교 → 이력 insert
  5. 수집 실패 : tb_law_clct_fail_hst 에 기록 (같은 수집일자·구분 재적재 시 교체)
  6. 이번에 새로 들어간 이력을 건별로 {logs_path}/{ymd}/load_hst_*.log 에 기록 (탭 구분)
  개정이력 insert 는 ON CONFLICT DO NOTHING (멱등). 개정이력·수집실패 테이블은 TRUNCATE 하지 않음
SQL 은 db/law_sql.py, 접속·점검은 db/connection.py
"""
from __future__ import annotations

import glob
import logging
import time
from datetime import datetime
from pathlib import Path

from common.utils import fmt_elapsed
from db import law_sql
from db.connection import connect
from db.connection import precheck as db_precheck

PGM_ID = 'load_csv'             # inpt_pgm_id / chg_pgm_id 값 (varchar(20) 이내)
MODES = ('full', 'incr')
# full 적재 시 이번 수집 법령 수가 기존 대비 이 비율 미만이면 TRUNCATE 하지 않고 중단 (목록 이상·대량 실패 방지)
FULL_MIN_RATIO = 0.9


def setup_logger(logs_path: str, ymd: str) -> logging.Logger:
    log_dir = Path(logs_path) / ymd
    log_dir.mkdir(parents=True, exist_ok=True)
    dt = datetime.now().strftime('%Y%m%d_%H%M%S')
    logger = logging.getLogger(f'load.{dt}')
    if not logger.handlers:
        fmt = logging.Formatter('[%(asctime)s] %(levelname)s %(message)s', '%Y-%m-%d %H:%M:%S')
        fh = logging.FileHandler(log_dir / f'load_{dt}.log', encoding='utf-8')
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(sh)
        logger.setLevel(logging.INFO)
    return logger


def precheck(cfg: dict, logger) -> None:
    db_precheck(cfg.get('db'), law_sql.expected_columns(), logger)


def _write_hst_log(conn, path: Path) -> int:
    """이번 트랜잭션에서 insert 된 이력을 파일로 (서버측 커서로 나눠 읽어 메모리 사용 제한)"""
    n = 0
    cur = conn.cursor(name='hst_log')
    cur.execute(law_sql.HST_LOG_SQL)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\t'.join(law_sql.HST_LOG_HEADER) + '\n')
        while True:
            rows = cur.fetchmany(10000)
            if not rows:
                break
            for r in rows:
                f.write('\t'.join('' if v is None else str(v) for v in r) + '\n')
            n += len(rows)
    cur.close()
    return n


def run(cfg: dict, ymd: str, mode: str, logger=None) -> None:
    if mode not in MODES:
        raise ValueError(f'mode 는 {MODES} 중 하나: {mode}')
    if logger is None:
        logger = setup_logger(cfg['logs_path'], ymd)
    csv_dir = Path(cfg['csv_path']) / ymd

    files = {}
    for table in law_sql.CSV_TABLES:
        files[table] = sorted(glob.glob(str(csv_dir / f'{table}_????_{ymd}.csv')))
        if not files[table]:
            raise FileNotFoundError(f'CSV 없음: {csv_dir}/{table}_????_{ymd}.csv')

    log_dir = Path(cfg['logs_path']) / ymd
    hst_log = log_dir / f"load_hst_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    hst_tmp = hst_log.with_suffix('.tmp')
    params = {'pgm_id': PGM_ID, 'clct_ymd': ymd, 'clct_dvs_nm': mode}
    logger.info(f'[load] 시작 | mode={mode} | CSV: {csv_dir}')

    conn = connect(cfg['db'])
    start = time.time()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout = 0")     # 대량 적재: 시간 제한 없음
        cur.execute("SET LOCAL work_mem = '256MB'")         # LAG 정렬용

        # 1. CSV → 임시테이블
        for table in law_sql.CSV_TABLES:
            cur.execute(law_sql.create_tmp_sql(table))
            rows = 0
            for fpath in files[table]:
                with open(fpath, 'rb') as f:
                    cur.copy_expert(law_sql.copy_sql(table), f)
                rows += cur.rowcount
            cur.execute(law_sql.delete_invalid_sql(table))
            if cur.rowcount:
                logger.warning(f'[load] {table}: 키/필수값 이상 행 {cur.rowcount:,}건 제외')
            logger.info(f'[load] {table}: CSV {rows:,}건 (파일 {len(files[table])}개)')

        # 2. anomaly (bas 덮어쓰기 전)
        cur.execute(law_sql.ANOMALY_ATCL_SQL, params)
        logger.info(f'[load] tb_law_atcl_amnd_hst anomaly 신규: {cur.rowcount:,}건')
        cur.execute(law_sql.ANOMALY_PARA_SQL, params)
        logger.info(f'[load] tb_law_para_amnd_hst anomaly 신규: {cur.rowcount:,}건')

        # 3. bas 반영
        if mode == 'full':
            cur.execute(law_sql.COUNT_BAS_SQL)
            db_laws, csv_laws = cur.fetchone()
            if db_laws and csv_laws < db_laws * FULL_MIN_RATIO:
                raise RuntimeError(f'[load] 이번 수집 법령 {csv_laws:,}건 < 기존 {db_laws:,}건의 {FULL_MIN_RATIO:.0%} '
                                   f'→ TRUNCATE 하지 않고 중단 (목록·본문 수집 결과 확인 필요)')
            cur.execute(law_sql.TRUNCATE_BAS_SQL)
            logger.info(f'[load] bas 3종 TRUNCATE (기존 tb_law_bas {db_laws:,}건)')
            for table in law_sql.BAS_TABLES:
                cur.execute(law_sql.upsert_sql(table), params)
                logger.info(f'[load] {table}: 적재 {cur.rowcount:,}건')
        else:
            for table in law_sql.BAS_TABLES:
                cur.execute(law_sql.count_new_sql(table))
                new_rows = cur.fetchone()[0]
                cur.execute(law_sql.upsert_sql(table), params)
                logger.info(f'[load] {table}: 신규 {new_rows:,}건 / 변경 {cur.rowcount - new_rows:,}건')
            cur.execute(law_sql.CLOSE_PREV_CURRENT_SQL, params)
            logger.info(f"[load] tb_law_bas: 이전 '현행' → '연혁' {cur.rowcount:,}건")

        # 4. amendment (bas 전체 기준)
        cur.execute(law_sql.AMENDMENT_ATCL_SQL, params)
        logger.info(f'[load] tb_law_atcl_amnd_hst amendment 신규: {cur.rowcount:,}건')
        cur.execute(law_sql.AMENDMENT_PARA_SQL, params)
        logger.info(f'[load] tb_law_para_amnd_hst amendment 신규: {cur.rowcount:,}건')

        # 5. 수집 실패 기록
        cur.execute(law_sql.DELETE_FAIL_SQL, params)
        cur.execute(law_sql.INSERT_FAIL_SQL, params)
        if cur.rowcount:
            logger.warning(f'[load] {law_sql.FAIL_TABLE}: 수집 실패 {cur.rowcount:,}건 기록 (이번 적재에서 제외됨)')
        else:
            logger.info(f'[load] {law_sql.FAIL_TABLE}: 수집 실패 0건')

        # 6. 이번에 판별·적재된 이력 건별 기록 (COMMIT 성공 후에만 최종 파일명으로)
        n_log = _write_hst_log(conn, hst_tmp)

        conn.commit()
        hst_tmp.rename(hst_log)
        logger.info(f'[load] 판별 이력 상세: {hst_log} ({n_log:,}건)')
        logger.info(f'[완료] load COMMIT | 소요: {fmt_elapsed(time.time() - start)}')

        cur = conn.cursor()
        cur.execute(law_sql.SUMMARY_SQL, params)
        for name, cnt in cur.fetchall():
            logger.info(f'[현황] {name}: {cnt:,}건')
    except Exception as e:
        conn.rollback()
        if hst_tmp.exists():
            hst_tmp.unlink()                 # 롤백됐으므로 상세 로그도 폐기
        logger.error(f'[ROLLBACK] load 실패 (DB 변경 없음) | 소요: {fmt_elapsed(time.time() - start)} | 원인: {e}')
        raise
    finally:
        conn.close()
