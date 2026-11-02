"""
law-collector-v2 : 법령 수집 → CSV → DB 적재

사용법:
  python main.py law_list   <env>
  python main.py law_detail <env>  [--concurrency N] [--test-urls URL ...]
  python main.py load       <env>  [--ymd YYYYMMDD]      (CSV → DB, 기본: 오늘 CSV)
  python main.py all        <env>  [--concurrency N]      (DB점검 → law_list → law_detail → load)

env: dev | stg | law | prod
출력: {csv_path}/{실행일}/*.csv , 로그: {logs_path}/{실행일}/

백그라운드 실행 (터미널 끊겨도 계속):
  nohup python3 main.py all <env> > all_$(date +%Y%m%d_%H%M).out 2>&1 &
"""
import argparse
import asyncio
import sys
import time
from datetime import date

from common.config import load_config
from common.logger import JobLogger
from common.utils import fmt_elapsed


def cmd_law_list(cfg: dict, ymd: str):
    from crawl.law_list import run
    logger = JobLogger(cfg['logs_path'], ymd, 'law_list')
    start = time.time()
    run(cfg, ymd, logger)
    logger.info(f'[law_list] 총 소요: {fmt_elapsed(time.time() - start)}')


def cmd_law_detail(cfg: dict, ymd: str, test_urls: list = None):
    from crawl.law_detail import run
    logger = JobLogger(cfg['logs_path'], ymd, 'law_detail')
    asyncio.run(run(cfg, ymd, logger, test_urls=test_urls))


def cmd_load(cfg: dict, ymd: str):
    from load_csv import precheck, run, setup_logger
    logger = setup_logger(cfg['logs_path'], ymd)
    precheck(cfg, logger)
    run(cfg, ymd, logger)


def cmd_all(cfg: dict, ymd: str):
    """ymd 는 실행 시작 시 고정 → 수집이 자정을 넘겨도 같은 날짜 폴더 CSV 를 적재"""
    from load_csv import precheck, run, setup_logger
    logger = setup_logger(cfg['logs_path'], ymd)
    precheck(cfg, logger)                    # DB/DDL 문제는 수집 전에 바로 실패
    cmd_law_list(cfg, ymd)
    cmd_law_detail(cfg, ymd)
    run(cfg, ymd, logger)


def main():
    parser = argparse.ArgumentParser(description='law-collector-v2 (법령 → CSV → DB)')
    sub = parser.add_subparsers(dest='command', required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('env', choices=['dev', 'stg', 'law', 'prod'])
    common.add_argument('--concurrency', type=int, help='동시연결 수 (기본: config.yml)')

    sub.add_parser('law_list', parents=[common], help='법령 목록 수집 (law_list CSV)')
    p_detail = sub.add_parser('law_detail', parents=[common], help='법령 본문 수집 (tb_law_bas/tb_law_atcl_bas/tb_law_para_bas CSV)')
    p_detail.add_argument('--test-urls', nargs='+', metavar='URL', dest='test_urls',
                          help='특정 URL 지정 수집 (테스트용)')
    p_load = sub.add_parser('load', parents=[common], help='CSV → DB 적재 (bas 3종 + 개정이력 2종)')
    p_load.add_argument('--ymd', help='적재할 CSV 날짜폴더 (기본: 오늘)')
    sub.add_parser('all', parents=[common], help='DB점검 → law_list → law_detail → load')

    args = parser.parse_args()
    cfg = load_config(args.env)
    if args.concurrency:
        cfg['concurrency'] = args.concurrency
    ymd = date.today().strftime('%Y%m%d')

    if args.command == 'law_list':
        cmd_law_list(cfg, ymd)
    elif args.command == 'law_detail':
        cmd_law_detail(cfg, ymd, getattr(args, 'test_urls', None))
    elif args.command == 'load':
        cmd_load(cfg, args.ymd or ymd)
    elif args.command == 'all':
        cmd_all(cfg, ymd)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
