"""PostgreSQL 접속 및 테이블 구조 점검 (업무 SQL 없음)"""
from __future__ import annotations

import psycopg2


def connect(db_cfg: dict):
    return psycopg2.connect(
        host=db_cfg.get('host', 'localhost'),
        port=int(db_cfg.get('port', 5432)),
        dbname=db_cfg['dbname'],
        user=db_cfg['user'],
        password=db_cfg.get('password', ''),
    )


def precheck(db_cfg: dict, expected_columns: dict, logger) -> None:
    """DB 접속 + 테이블/컬럼 존재 확인. 문제가 있으면 예외 → 수집·적재 시작 전에 바로 실패"""
    if not db_cfg:
        raise RuntimeError('config.yml 에 db 설정이 없습니다')
    conn = connect(db_cfg)
    try:
        cur = conn.cursor()
        cur.execute('SHOW timezone')
        tz = cur.fetchone()[0]
        if tz not in ('Asia/Seoul', 'ROK'):
            logger.warning(f'[precheck] DB timezone={tz} → inpt_dt/chg_dt/detected_dt 가 KST 와 어긋남 (DB 설정으로 처리 필요)')

        problems = []
        for table, cols in expected_columns.items():
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = %s", (table,))
            have = {r[0] for r in cur.fetchall()}
            if not have:
                problems.append(f'{table}: 테이블 없음')
            elif set(cols) - have:
                problems.append(f'{table}: 컬럼 없음 {sorted(set(cols) - have)}')
        if problems:
            raise RuntimeError('[precheck] DDL 불일치 → ' + ' / '.join(problems))
        logger.info(f'[precheck] DB 접속·테이블 {len(expected_columns)}개 확인 OK (db={db_cfg["dbname"]}, timezone={tz})')
    finally:
        conn.close()
