import logging
from datetime import datetime
from pathlib import Path


class JobLogger:
    def __init__(self, logs_path: str, ymd: str, task: str = ''):
        self._log_dir = Path(logs_path) / ymd
        self._log_dir.mkdir(parents=True, exist_ok=True)

        prefix = f'{task}_' if task else ''
        dt = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.final_fail_log = self._log_dir / f'final_fail_{prefix}{dt}.log'

        # link 실패 로그: 파일을 한 번 열고 유지 (라인 단위 자동 flush)
        self._link_file = open(
            self._log_dir / f'link_{prefix}{dt}.log', 'a', encoding='utf-8', buffering=1
        )

        fmt = logging.Formatter('[%(asctime)s] %(levelname)s %(message)s', '%Y-%m-%d %H:%M:%S')
        logger_name = f'law.{ymd}.{task}' if task else f'law.{ymd}'
        self._logger = logging.getLogger(logger_name)
        if not self._logger.handlers:
            sh = logging.StreamHandler()
            sh.setFormatter(fmt)
            fh = logging.FileHandler(self._log_dir / f'crawl_{prefix}{dt}.log', encoding='utf-8')
            fh.setFormatter(fmt)
            self._logger.addHandler(sh)
            self._logger.addHandler(fh)
            self._logger.setLevel(logging.INFO)

    def log_link_fail(self, url: str, error: str, done: int, total: int):
        pct = done / total * 100 if total else 0
        self._link_file.write(
            f'[{datetime.now():%Y-%m-%d %H:%M:%S}] FAIL    ({done:>6}/{total}, {pct:5.1f}%) {url} | {error}\n'
        )

    def save_final_fails(self, fail_list: list, elapsed: str):
        with open(self.final_fail_log, 'w', encoding='utf-8') as f:
            f.write(f'# 총 실패: {len(fail_list)}건 | 소요시간: {elapsed}\n')
            for meta in fail_list:
                f.write(meta.get('link', str(meta)) + '\n')

    def info(self, msg: str):
        self._logger.info(msg)

    def warning(self, msg: str):
        self._logger.warning(msg)

    def error(self, msg: str):
        self._logger.error(msg)

    def close(self):
        self._link_file.close()
