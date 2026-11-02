from __future__ import annotations

import asyncio
import csv
import re
import sys
import time
import traceback
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_random_exponential, retry_if_exception_type
from tqdm import tqdm

from common.csv_writer import CsvWriter
from common.http_client import fetch_xml, make_async_client, RETRYABLE
from common.logger import JobLogger
from common.utils import ctxt_hash, extract_amnd_info, fmt_elapsed
from common.xml_parser import (
    convert_circled_number, get_tag, get_tag_attr_and_value,
    get_tag_value, make_brch_no, parse_xml_string,
)

# ── CSV 헤더 (v2 DDL 컬럼 순서. 공통 4컬럼 inpt_*/chg_* 는 적재 단계에서 채움) ──
TB_LAW_BAS_HEADERS = [
    'LAW_ENFC_ID', 'LAW_SEQ', 'ENFC_YMD', 'LAW_ID', 'ENTRVS_DVS_CD', 'ENTRVS_DVS_NM',
    'PRMLGT_YMD', 'PRMLGT_NO', 'CRNT_LAW_NM', 'URL_PATH_NM', 'ATCL_DVS_NM',
    'LAW_CTXT', 'LAW_DVS_CD_NM', 'LAW_KOR_NM', 'LAW_ABRVTD_NM',
]
# AMND_YMD, AMND_TYP_NM 은 bas 테이블에 없는 컬럼 → 적재 시 임시테이블에서만 사용 (이력 기록용)
TB_LAW_ATCL_BAS_HEADERS = [
    'LAW_ENFC_ID', 'LAW_BRCH_NO', 'LAW_SEQ', 'ENFC_YMD', 'LAW_ID', 'ATCL_NO',
    'ATCL_TITLE', 'ATCL_CTXT', 'ATCL_CTXT_HSID', 'AMND_RSN_CTXT', 'ATCL_DVS_NM',
    'ATCL_CHG_YN', 'SUPP_PROV_CTXT', 'SUPP_PROV_PRMLGT_YMD', 'SUPP_PROV_PRMLGT_NO',
    'AMND_YMD', 'AMND_TYP_NM',
]
TB_LAW_PARA_BAS_HEADERS = [
    'LAW_ENFC_ID', 'LAW_BRCH_NO', 'PARA_NO', 'LAW_SEQ', 'ENFC_YMD', 'LAW_ID', 'ATCL_NO',
    'PARA_TITLE', 'PARA_CTXT', 'PARA_CTXT_HSID', 'AMND_RSN_CTXT', 'ATCL_CHG_YN',
    'SUPP_PROV_CTXT', 'SUPP_PROV_PRMLGT_YMD', 'SUPP_PROV_PRMLGT_NO',
    'AMND_YMD', 'AMND_TYP_NM',
]


# ── law_list CSV → meta 목록 로드 ────────────────────────────────────────────
def load_metas(csv_dir: Path) -> list:
    files = sorted(csv_dir.glob('law_list_????_*.csv'))
    if not files:
        raise FileNotFoundError(f'law_list CSV 없음: {csv_dir}/law_list_????_*.csv')
    metas = []
    for f in files:
        with open(f, 'r', encoding='utf-8') as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                url_path_nm = row.get('URL_PATH_NM', '').strip()
                if url_path_nm:
                    metas.append({
                        'url_path_nm':   url_path_nm,
                        'law_seq':       row.get('LAW_SEQ', '').strip(),
                        'crnt_law_nm':   row.get('CRNT_LAW_NM', '').strip(),
                        'entrvs_dvs_cd': row.get('ENTRVS_DVS_CD', '').strip(),
                        'entrvs_dvs_nm': row.get('ENTRVS_DVS_NM', '').strip(),
                    })
    return metas


# ── 공통 기본정보 추출 ────────────────────────────────────────────────────────
def _raw_text(root, tag: str) -> str:
    """부칙·제개정이유용: 공백/개행 보존한 원문 (같은 태그 여러 개면 개행으로 연결)"""
    return '\n'.join(''.join(el.itertext()).strip() for el in root.findall('.//' + tag)).strip()


def _supp_prov(root, prmlgt_ymd: str, prmlgt_no: str) -> dict:
    """법령의 공포일자/공포번호와 일치하는 부칙단위. 없으면 마지막 부칙단위 (지침 4.5)"""
    units = root.findall('.//부칙단위')
    if not units:
        return {'supp_prov_ctxt': '', 'supp_prov_prmlgt_ymd': '', 'supp_prov_prmlgt_no': '', 'matched': True}
    picked, matched = units[-1], False
    for u in units:
        # 부칙공포번호는 0패딩(예: 08761)으로 오므로 앞자리 0 제거 후 비교
        if get_tag_value(u, '부칙공포일자') == prmlgt_ymd and get_tag_value(u, '부칙공포번호').lstrip('0') == prmlgt_no.lstrip('0'):
            picked, matched = u, True
            break
    return {
        'supp_prov_ctxt':       _raw_text(picked, '부칙내용'),
        'supp_prov_prmlgt_ymd': get_tag_value(picked, '부칙공포일자'),
        'supp_prov_prmlgt_no':  get_tag_value(picked, '부칙공포번호'),
        'matched': matched,
    }


def _base(root, meta: dict) -> dict:
    law_type = get_tag_attr_and_value(root, '법종구분', '법종구분코드')
    law_seq = meta['law_seq']
    if not law_seq:                         # --test-urls 모드: URL 의 MST 값 사용
        m = re.search(r'MST=(\d+)', meta['url_path_nm'])
        law_seq = m.group(1) if m else ''
    b = {
        'law_id':        get_tag_value(root, '법령ID'),
        'law_seq':       law_seq,
        'prmlgt_ymd':    get_tag_value(root, '공포일자'),
        'prmlgt_no':     get_tag_value(root, '공포번호'),
        'law_kor_nm':    get_tag_value(root, '법령명_한글'),
        'law_abrvtd_nm': get_tag_value(root, '법령명약칭'),
        'enfc_ymd':      get_tag_value(root, '시행일자'),
        'crnt_law_nm':   meta['crnt_law_nm'],
        'law_dvs_cd_nm': law_type['text'],
        'entrvs_dvs_cd': meta.get('entrvs_dvs_cd', ''),
        'entrvs_dvs_nm': meta.get('entrvs_dvs_nm', ''),
        'url_path_nm':   meta['url_path_nm'],
        'amnd_rsn_ctxt': _raw_text(root, '제개정이유내용'),
    }
    b['law_enfc_id'] = f"{b['law_seq']}{b['enfc_ymd']}"      # 법령일련번호+시행일자 (구분자 없음)
    b['supp'] = _supp_prov(root, b['prmlgt_ymd'], b['prmlgt_no'])
    return b


def _build_hang_ho_mok(jomun_el) -> list:
    lines = []
    for hang in jomun_el.findall('.//항'):
        hang_con = get_tag(hang, '항내용')
        if hang_con:
            lines.append(hang_con.strip())
        for ho in hang.findall('.//호'):
            ho_con = get_tag(ho, '호내용')
            if ho_con:
                lines.append(ho_con.strip())
            for mok in ho.findall('.//목'):
                mok_con = get_tag(mok, '목내용')
                if mok_con:
                    lines.append(mok_con.strip())
    return lines


# ── tb_law_bas 파싱 (법령단위: URL 1개 → 행 1개) ────────────────────────────
def parse_law_bas(root, b: dict):
    jomun_field = root.find('.//조문')
    if jomun_field is None:
        return None
    jomun_list = jomun_field.findall('조문단위')
    if not jomun_list:
        return None

    jb = []
    atcl_dvs_nm = ''                         # 첫 조문단위의 조문여부 (전문/조문)
    for jomun in jomun_list:
        jomun_con = get_tag(jomun, '조문내용')
        if not jomun_con:
            continue

        jomun_yn = get_tag(jomun, '조문여부')
        if not atcl_dvs_nm and jomun_yn:
            atcl_dvs_nm = jomun_yn

        jb.append(jomun_con)                 # v2: 장·절 제목(전문)도 본문에 남김 (지침 4.1)
        if jomun_yn == '조문':
            jb.extend(_build_hang_ho_mok(jomun))
    law_ctxt = '\n'.join(jb)

    return [
        b['law_enfc_id'], b['law_seq'], b['enfc_ymd'], b['law_id'],
        b['entrvs_dvs_cd'], b['entrvs_dvs_nm'], b['prmlgt_ymd'], b['prmlgt_no'],
        b['crnt_law_nm'], b['url_path_nm'], atcl_dvs_nm, law_ctxt,
        b['law_dvs_cd_nm'], b['law_kor_nm'], b['law_abrvtd_nm'],
    ]


# ── tb_law_atcl_bas 파싱 (조문단위: URL 1개 → 행 N개) ──────────────────────
def parse_law_atcl(root, b: dict) -> list:
    jomun_field = root.find('.//조문')
    if jomun_field is None:
        return []
    jomun_list = jomun_field.findall('조문단위')
    if not jomun_list:
        return []

    result = {}
    for jomun in jomun_list:
        jomun_con = get_tag(jomun, '조문내용')
        if not jomun_con:
            continue

        jomun_no     = get_tag(jomun, '조문번호')
        jomun_ser_no = get_tag(jomun, '조문가지번호')
        jomun_yn     = get_tag(jomun, '조문여부')
        jomun_chg_yn = get_tag(jomun, '조문변경여부')
        jomun_title  = get_tag(jomun, '조문제목')
        jomun_title  = f'({jomun_title})' if jomun_title else ''
        jomun_ref    = get_tag(jomun, '조문참고자료')   # [본조신설 ..] [제목개정 ..] 등. 본문엔 미포함, 태그 추출에만 사용

        law_brch_no = make_brch_no(jomun_no, jomun_ser_no)
        jo_con_no = (f'제{jomun_no}조의{jomun_ser_no}' if jomun_ser_no else f'제{jomun_no}조') if jomun_no and jomun_no != '0' else ''

        if jomun_yn == '조문':
            atcl_ctxt = '\n'.join([jomun_con] + _build_hang_ho_mok(jomun))
            result.setdefault(law_brch_no, {
                'atcl_no': int(law_brch_no[:4]), 'atcl_dvs_nm': jomun_yn,
                'atcl_title': ' '.join(filter(None, [b['law_kor_nm'], jo_con_no, jomun_title])),
                'atcl_ctxt': atcl_ctxt, 'atcl_chg_yn': jomun_chg_yn, 'jomun_ref': jomun_ref,
            })
        elif len(jomun_list) == 1:           # v1 동일: 조문단위 1개뿐인 법령은 0000000 으로 적재
            result.setdefault('0000000', {
                'atcl_no': 0, 'atcl_dvs_nm': jomun_yn,
                'atcl_title': b['law_kor_nm'],
                'atcl_ctxt': jomun_con, 'atcl_chg_yn': jomun_chg_yn, 'jomun_ref': jomun_ref,
            })

    sp = b['supp']
    rows = []
    for law_brch_no, rd in result.items():
        amnd_ymd, amnd_typ_nm = extract_amnd_info(rd['atcl_ctxt'] + '\n' + rd['jomun_ref'])
        rows.append([
            b['law_enfc_id'], law_brch_no, b['law_seq'], b['enfc_ymd'], b['law_id'], rd['atcl_no'],
            rd['atcl_title'], rd['atcl_ctxt'], ctxt_hash(rd['atcl_ctxt']), b['amnd_rsn_ctxt'], rd['atcl_dvs_nm'],
            rd['atcl_chg_yn'], sp['supp_prov_ctxt'], sp['supp_prov_prmlgt_ymd'], sp['supp_prov_prmlgt_no'],
            amnd_ymd, amnd_typ_nm,
        ])
    return rows


# ── tb_law_para_bas 파싱 (항단위: URL 1개 → 행 N개) ────────────────────────
def parse_law_para(root, b: dict) -> list:
    jomun_field = root.find('.//조문')
    if jomun_field is None:
        return []
    jomun_list = jomun_field.findall('조문단위')
    if not jomun_list:
        return []

    result = {}
    for jomun in jomun_list:
        jomun_no     = get_tag(jomun, '조문번호')
        jomun_ser_no = get_tag(jomun, '조문가지번호')
        jomun_con    = get_tag(jomun, '조문내용')
        jomun_yn     = get_tag(jomun, '조문여부')
        jomun_chg_yn = get_tag(jomun, '조문변경여부')
        jomun_title  = get_tag(jomun, '조문제목')
        jomun_title  = f'({jomun_title})' if jomun_title else ''
        jomun_ref    = get_tag(jomun, '조문참고자료')   # [본조신설 ..] [제목개정 ..] 등. 본문엔 미포함, 태그 추출에만 사용

        law_brch_no = make_brch_no(jomun_no, jomun_ser_no)
        jo_con_no = (f'제{jomun_no}조의{jomun_ser_no}' if jomun_ser_no else f'제{jomun_no}조') if jomun_no and jomun_no != '0' else ''

        def _process_hangs(hang_list, law_brch_no_val, atcl_no_val, jo_con_no_val):
            for hang_el in hang_list:
                para_no = convert_circled_number(get_tag(hang_el, '항번호')).strip()
                if not para_no or not para_no.isdigit():
                    continue                 # 항번호 없는 항은 적재하지 않음 (지침 4.7, v1 동일)
                para_no_nm = f'제{para_no}항' if para_no != '0' else ''

                all_hang = []
                hang_con = get_tag(hang_el, '항내용').strip()
                if hang_con:
                    all_hang.append(hang_con)
                for ho in hang_el.findall('.//호'):
                    ho_con = get_tag(ho, '호내용')
                    if ho_con:
                        all_hang.append(ho_con.strip())
                    for mok in ho.findall('.//목'):
                        mok_con = get_tag(mok, '목내용')
                        if mok_con:
                            all_hang.append(mok_con.strip())

                own = '\n'.join(all_hang)   # 항 자체 본문 (해시 기준)
                para_ctxt = '\r\n'.join(filter(None, [jomun_con, own]))
                result.setdefault((law_brch_no_val, int(para_no)), {
                    'atcl_no': atcl_no_val,
                    'para_title': ' '.join(filter(None, [b['law_kor_nm'], jo_con_no_val, para_no_nm, jomun_title])),
                    'para_ctxt': para_ctxt, 'para_ctxt_hsid': ctxt_hash(own),
                    'atcl_chg_yn': jomun_chg_yn, 'jomun_ref': jomun_ref,
                })

        hang_list = jomun.findall('.//항')
        if jomun_yn == '조문':
            _process_hangs(hang_list, law_brch_no, int(law_brch_no[:4]), jo_con_no)
        elif len(jomun_list) == 1:
            _process_hangs(hang_list, '0000000', 0, '')

    sp = b['supp']
    rows = []
    for (law_brch_no, para_no), rd in result.items():
        amnd_ymd, amnd_typ_nm = extract_amnd_info(rd['para_ctxt'] + '\n' + rd['jomun_ref'])
        rows.append([
            b['law_enfc_id'], law_brch_no, para_no, b['law_seq'], b['enfc_ymd'], b['law_id'], rd['atcl_no'],
            rd['para_title'], rd['para_ctxt'], rd['para_ctxt_hsid'], b['amnd_rsn_ctxt'], rd['atcl_chg_yn'],
            sp['supp_prov_ctxt'], sp['supp_prov_prmlgt_ymd'], sp['supp_prov_prmlgt_no'],
            amnd_ymd, amnd_typ_nm,
        ])
    return rows


PROGRESS_SEC = 60                # 진행 로그 간격 (초)
MAX_CONSECUTIVE_FAIL = 500       # 연속 실패가 이만큼 쌓이면 중단 (코드 오류·API 차단 시 전체를 헛돌지 않도록)


# ── 메인 실행 ────────────────────────────────────────────────────────────────
async def run(cfg: dict, ymd: str, logger: JobLogger, test_urls: list = None):
    csv_dir = Path(cfg['csv_path']) / ymd
    csv_dir.mkdir(parents=True, exist_ok=True)

    if test_urls:
        metas = [{'url_path_nm': u, 'law_seq': '', 'crnt_law_nm': '', 'entrvs_dvs_cd': '', 'entrvs_dvs_nm': ''} for u in test_urls]
        logger.info(f'[law_detail] 테스트 URL {len(metas)}건 지정')
    else:
        try:
            metas = load_metas(csv_dir)
        except Exception as exc:
            logger.error(f'[law_detail] law_list CSV 로드 실패: {exc}')
            raise
        logger.info(f'[law_detail] 대상 URL: {len(metas)}건')
    total = len(metas)

    writers = {
        'tb_law_bas':      CsvWriter('tb_law_bas',      csv_dir, TB_LAW_BAS_HEADERS,      cfg['batch_size'], ymd, logger),
        'tb_law_atcl_bas': CsvWriter('tb_law_atcl_bas', csv_dir, TB_LAW_ATCL_BAS_HEADERS, cfg['batch_size'], ymd, logger),
        'tb_law_para_bas': CsvWriter('tb_law_para_bas', csv_dir, TB_LAW_PARA_BAS_HEADERS, cfg['batch_size'], ymd, logger),
    }

    fail_list = []
    supp_fallback = []                       # 부칙 공포번호 매칭 실패 → 마지막 부칙단위 사용한 법령
    done_count = 0
    consecutive_fail = 0
    seen_error_types = set()                 # 에러 종류별 첫 발생만 Traceback 기록
    aborted = False
    start_time = time.time()
    last_log_time = start_time

    async with make_async_client(verify_ssl=(cfg['env'] != 'dev')) as client:

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_random_exponential(multiplier=1, min=2, max=15),
            retry=retry_if_exception_type(RETRYABLE),
            reraise=True,
        )
        async def _fetch_and_parse(url: str):
            return parse_xml_string(await fetch_xml(client, url))

        q: asyncio.Queue = asyncio.Queue()
        for m in metas:
            q.put_nowait(m)

        seen = {'tb_law_bas': set(), 'tb_law_atcl_bas': set(), 'tb_law_para_bas': set()}
        # 백그라운드(nohup) 실행 시 진행바 끔 → PROGRESS_SEC 마다 진행 로그
        with tqdm(total=total, desc='[law_detail]', unit='건', disable=not sys.stderr.isatty()) as pbar:

            def _log_progress():
                elapsed_sec = time.time() - start_time
                rate = done_count / elapsed_sec if elapsed_sec else 0
                remain = fmt_elapsed((total - done_count) / rate) if rate else '-'
                logger.info(f'[law_detail] 진행: {done_count:,}/{total:,}건 ({done_count * 100 / total:.1f}%) '
                            f'| 실패: {len(fail_list):,}건 | {rate:.1f}건/초 | 남은 예상: {remain}')

            async def worker():
                nonlocal done_count, consecutive_fail, aborted, last_log_time
                while not aborted:
                    try:
                        meta = q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    try:
                        root = await _fetch_and_parse(meta['url_path_nm'])

                        b = _base(root, meta)
                        bas_row   = parse_law_bas(root, b)
                        atcl_rows = parse_law_atcl(root, b)
                        para_rows = parse_law_para(root, b)
                        if not b['supp']['matched']:
                            supp_fallback.append(b['law_enfc_id'])

                        if bas_row and bas_row[0] not in seen['tb_law_bas']:
                            seen['tb_law_bas'].add(bas_row[0])
                            writers['tb_law_bas'].put(bas_row)
                        for r in atcl_rows:
                            key = (r[0], r[1])                  # law_enfc_id, law_brch_no
                            if key not in seen['tb_law_atcl_bas']:
                                seen['tb_law_atcl_bas'].add(key)
                                writers['tb_law_atcl_bas'].put(r)
                        for r in para_rows:
                            key = (r[0], r[1], r[2])            # + para_no
                            if key not in seen['tb_law_para_bas']:
                                seen['tb_law_para_bas'].add(key)
                                writers['tb_law_para_bas'].put(r)

                        consecutive_fail = 0

                    except Exception as exc:
                        fail_list.append(meta)
                        consecutive_fail += 1
                        logger.log_link_fail(meta['url_path_nm'], f'{type(exc).__name__}: {exc}', done_count, total)
                        if type(exc).__name__ not in seen_error_types:        # 에러 위치(파일·줄번호) 확인용
                            seen_error_types.add(type(exc).__name__)
                            logger.error(f'[law_detail] 첫 {type(exc).__name__} 발생 ({meta["url_path_nm"]})\n{traceback.format_exc()}')
                        if consecutive_fail >= MAX_CONSECUTIVE_FAIL and not aborted:
                            aborted = True
                            logger.error(f'[law_detail] 연속 실패 {consecutive_fail}건 → 수집 중단 (위 Traceback 확인)')
                    finally:
                        done_count += 1
                        pbar.update(1)
                        pbar.set_postfix({'실패': len(fail_list)})
                        if time.time() - last_log_time >= PROGRESS_SEC:
                            last_log_time = time.time()
                            _log_progress()

            await asyncio.gather(*[worker() for _ in range(cfg['concurrency'])])

    for w in writers.values():
        w.close()

    elapsed = fmt_elapsed(time.time() - start_time)

    if fail_list:
        logger.save_final_fails(fail_list, elapsed)
    if aborted:                              # 예외로 종료 → all 실행 시 load 로 넘어가지 않음
        raise RuntimeError(f'[law_detail] 연속 실패로 중단 ({done_count:,}/{total:,}건 처리, 실패 {len(fail_list):,}건)')

    if supp_fallback:
        logger.warning(f'[law_detail] 부칙 공포번호 매칭 실패 → 마지막 부칙단위 사용: {len(supp_fallback):,}건 (예: {supp_fallback[:5]})')

    wb = writers['tb_law_bas']
    wa = writers['tb_law_atcl_bas']
    wp = writers['tb_law_para_bas']
    logger.info(
        f'[완료] law_detail | 수집: {total - len(fail_list):,}/{total:,}건 | 실패: {len(fail_list):,}건 | 소요: {elapsed}'
        f' | tb_law_bas: {wb.total_rows:,}건/{wb.file_count}개 | tb_law_atcl_bas: {wa.total_rows:,}건/{wa.file_count}개 | tb_law_para_bas: {wp.total_rows:,}건/{wp.file_count}개'
    )
