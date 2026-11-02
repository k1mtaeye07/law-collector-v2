import csv
import glob
import queue
import threading
import traceback
from datetime import date
from pathlib import Path


def _cleanup_old_csv(csv_dir: Path, today: str) -> int:
    """
    csv_dir 날짜 디렉토리(YYYYMMDD) 중 어제까지 csv디렉토리를 삭제한다. 삭제 후 파일 수 반환.
    구조: {csv_path}/{ymd}/  →  csv_dir.parent = {csv_path}/
    """
    deleted = 0
    base = csv_dir.parent  # {csv_path}/
    for vol_dir in base.iterdir():
        if not vol_dir.is_dir():
            continue
        name = vol_dir.name
        if name.isdigit() and len(name) == 8 and name < today:
            for f in vol_dir.glob('*.csv'):
                f.unlink()
                deleted += 1
            try:
                vol_dir.rmdir()  # CSV 삭제 후 디렉토리가 비었으면 제거
            except OSError:
                pass             # 로그 파일 등 다른 파일이 남아있으면 그냥 두기
    return deleted


class CsvWriter:
    """
    queue.Queue 기반 CSV 파일 writer.
    asyncio 루프와 분리된 별도 writer 스레드에서 동작.
    배치 크기 초과 시 자동으로 다음 파일로 분할.
    파일명: {job_name}_{idx:04d}_{ymd}.csv
    """

    _SENTINEL = object()

    def __init__(self, job_name: str, csv_dir: Path, headers: list, batch_size: int, ymd: str = None, logger=None):
        self.job_name = job_name
        self.csv_dir = csv_dir
        self.headers = headers
        self.batch_size = batch_size
        self.ymd = ymd or date.today().strftime('%Y%m%d')
        self._logger = logger

        self._q: queue.Queue = queue.Queue()
        self._file_idx = 1
        self._rows_in_file = 0
        self._total_rows = 0
        self._current_file = None
        self._writer = None

        # 과거 날짜 CSV 전체 삭제 (용량 관리: 어제 이전 파일 제거)
        _cleanup_old_csv(csv_dir, self.ymd)

        # 동일 테이블의 오늘 CSV 정리 (재실행 시 stale 파일 방지)
        for old in glob.glob(str(csv_dir / f'{job_name}_????_*.csv')):
            Path(old).unlink()

        self._thread = threading.Thread(target=self._loop, daemon=True, name=f'csv-{job_name}')
        self._thread.start()

    def put(self, row: list):
        self._q.put(row)

    def close(self):
        self._q.put(self._SENTINEL)
        self._thread.join()

    @property
    def total_rows(self) -> int:
        return self._total_rows

    @property
    def file_count(self) -> int:
        return self._file_idx - (1 if self._rows_in_file == 0 else 0)

    def _open_file(self):
        fname = self.csv_dir / f'{self.job_name}_{self._file_idx:04d}_{self.ymd}.csv'
        self._current_file = open(fname, 'w', newline='', encoding='utf-8')
        self._writer = csv.writer(self._current_file, quoting=csv.QUOTE_ALL)
        self._writer.writerow(self.headers)
        self._rows_in_file = 0

    def _close_file(self):
        if self._current_file:
            self._current_file.flush()
            self._current_file.close()
            self._current_file = None

    def _loop(self):
        try:
            self._open_file()
            while True:
                row = self._q.get()
                if row is self._SENTINEL:
                    break
                # normalize newlines in each field
                normalized = [
                    v.replace('\r\n', '\n').replace('\r', '\n') if isinstance(v, str) else (v or '')
                    for v in row
                ]
                self._writer.writerow(normalized)
                self._rows_in_file += 1
                self._total_rows += 1

                if self._rows_in_file >= self.batch_size:
                    self._close_file()
                    self._file_idx += 1
                    self._open_file()
        except Exception as exc:
            msg = f'[CsvWriter/{self.job_name}] 스레드 오류: {exc}\n{traceback.format_exc()}'
            if self._logger is not None:
                self._logger.error(msg)
            else:
                import logging
                logging.getLogger('csv_writer').error(msg)
        finally:
            self._close_file()
