"""
law-collector-v2 : 법령 수집 → CSV → DB 적재

사용법:
  python main.py all        <env>  [--concurrency N]                (전체: DB점검 → law_list → law_detail → load full)
  python main.py incr       <env>  --efyd YYYYMMDD~YYYYMMDD [--concurrency N]
                                                                   (증분: DB점검 → law_list(시행일자 범위) → law_detail → load incr)
  python main.py law_list   <env>  [--efyd YYYYMMDD~YYYYMMDD]       (--efyd 있으면 incr, 없으면 full 폴더)
  python main.py law_detail <env>  --mode full|incr [--concurrency N] [--test-urls URL ...]
  python main.py load       <env>  --mode full|incr [--ymd YYYYMMDD]   (CSV → DB, 기본: 오늘 CSV)

env: dev | stg | law | prod
출력: {csv_path}/{실행일}/{full|incr}/*.csv , 로그: {logs_path}/{실행일}/{full|incr}/

백그라운드 실행 (터미널 끊겨도 계속):
  nohup python3 main.py all <env> > all_$(date +%Y%m%d_%H%M).out 2>&1 &
"""
import argparse
import asyncio
import re
import sys
import time
from datetime import date

from common.config import load_config
from common.logger import JobLogger
from common.utils import fmt_elapsed


def _efyd(value: str) -> str:
    """시행일자 범위 YYYYMMDD~YYYYMMDD (단일 날짜 YYYYMMDD 는 같은 날~같은 날로)"""
    if re.fullmatch(r'\d{8}', value):
        value = f'{value}~{value}'
    m = re.fullmatch(r'(\d{8})~(\d{8})', value)
    if not m or m.group(1) > m.group(2):
        raise argparse.ArgumentTypeError(f'시행일자 범위 형식 오류: {value} (예: 20261109~20261110)')
    return value


def cmd_law_list(cfg: dict, ymd: str, mode: str, efyd: str = None):
    from crawl.law_list import run
    logger = JobLogger(cfg['logs_path'], ymd, mode, 'law_list')
    start = time.time()
    run(cfg, ymd, mode, logger, efyd=efyd)
    logger.info(f'[law_list] 총 소요: {fmt_elapsed(time.time() - start)}')


def cmd_law_detail(cfg: dict, ymd: str, mode: str, test_urls: list = None):
    from crawl.law_detail import run
    logger = JobLogger(cfg['logs_path'], ymd, mode, 'law_detail')
    asyncio.run(run(cfg, ymd, mode, logger, test_urls=test_urls))


def cmd_load(cfg: dict, ymd: str, mode: str):
    from load_csv import precheck, run, setup_logger
    logger = setup_logger(cfg['logs_path'], ymd, mode)
    precheck(cfg, logger)
    run(cfg, ymd, mode, logger)


def cmd_collect(cfg: dict, ymd: str, mode: str, efyd: str = None):
    """수집~적재 일괄. ymd 는 실행 시작 시 고정 → 수집이 자정을 넘겨도 같은 날짜 폴더 CSV 를 적재"""
    from load_csv import precheck, run, setup_logger
    logger = setup_logger(cfg['logs_path'], ymd, mode)
    logger.info(f'[{mode}] 시작' + (f' | 시행일자 범위: {efyd}' if efyd else ''))
    precheck(cfg, logger)                    # DB/DDL 문제는 수집 전에 바로 실패
    cmd_law_list(cfg, ymd, mode, efyd)
    cmd_law_detail(cfg, ymd, mode)
    run(cfg, ymd, mode, logger)


def main():
    parser = argparse.ArgumentParser(description='law-collector-v2 (법령 → CSV → DB)')
    sub = parser.add_subparsers(dest='command', required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('env', choices=['dev', 'stg', 'law', 'prod'])
    common.add_argument('--concurrency', type=int, help='동시연결 수 (기본: config.yml)')

    sub.add_parser('all', parents=[common], help='전체 수집: DB점검 → law_list → law_detail → load full (TRUNCATE)')
    p_incr = sub.add_parser('incr', parents=[common], help='증분 수집: DB점검 → law_list(시행일자 범위) → law_detail → load incr')
    p_incr.add_argument('--efyd', type=_efyd, required=True, metavar='YYYYMMDD~YYYYMMDD', help='시행일자 범위')
    p_list = sub.add_parser('law_list', parents=[common], help='법령 목록 수집 (law_list CSV)')
    p_list.add_argument('--efyd', type=_efyd, metavar='YYYYMMDD~YYYYMMDD', help='시행일자 범위 (없으면 전체)')
    p_detail = sub.add_parser('law_detail', parents=[common], help='법령 본문 수집 (tb_law_* CSV)')
    p_detail.add_argument('--mode', choices=['full', 'incr'], required=True,
                          help='읽을 law_list·쓸 CSV 폴더 ({실행일}/full 또는 {실행일}/incr)')
    p_detail.add_argument('--test-urls', nargs='+', metavar='URL', dest='test_urls',
                          help='특정 URL 지정 수집 (테스트용)')
    p_load = sub.add_parser('load', parents=[common], help='CSV → DB 적재')
    p_load.add_argument('--mode', choices=['full', 'incr'], required=True,
                        help='full: bas TRUNCATE 후 적재 / incr: UPSERT')
    p_load.add_argument('--ymd', help='적재할 CSV 날짜폴더 (기본: 오늘)')

    args = parser.parse_args()
    cfg = load_config(args.env)
    if args.concurrency:
        cfg['concurrency'] = args.concurrency
    ymd = date.today().strftime('%Y%m%d')

    if args.command == 'all':
        cmd_collect(cfg, ymd, 'full')
    elif args.command == 'incr':
        cmd_collect(cfg, ymd, 'incr', args.efyd)
    elif args.command == 'law_list':
        cmd_law_list(cfg, ymd, 'incr' if args.efyd else 'full', args.efyd)
    elif args.command == 'law_detail':
        cmd_law_detail(cfg, ymd, args.mode, getattr(args, 'test_urls', None))
    elif args.command == 'load':
        cmd_load(cfg, args.ymd or ymd, args.mode)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
