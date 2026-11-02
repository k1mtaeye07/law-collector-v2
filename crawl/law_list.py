import re
import requests
from pathlib import Path
from urllib.parse import urlparse

from tqdm import tqdm

from common.csv_writer import CsvWriter
from common.logger import JobLogger
from common.xml_parser import parse_xml_string, get_list_tag_value

LAW_TG = 'eflaw'

HEADERS = [
    'LAW_ENFC_ID', 'LAW_SRNO', 'LAW_ID', 'ENTRVS_DVS_CD', 'ENTRVS_DVS_NM',
    'PRMLGT_YMD', 'PRMLGT_NO', 'LAW_HAN_NM', 'ENFC_YMD', 'CRNT_LAW_NM', 'LINK',
]

ENTRVS_DVS_CD_MAP = {
    '제정':   '300201',
    '일부개정': '300202',
    '전부개정': '300203',
    '폐지':   '300204',
    '폐지제정': '300205',
    '일괄개정': '300206',
    '일괄폐지': '300207',
    '기타':   '300208',
    '타법개정': '300209',
    '타법폐지': '300210',
}


def _call_api(url: str, verify_ssl: bool = True) -> object:
    resp = requests.get(url, verify=verify_ssl, timeout=30)
    resp.raise_for_status()
    return parse_xml_string(resp.content)


def _adjust_url(detail_url: str, base_url: str) -> str:
    """법령상세링크(상대경로)를 api_con_path 기반 절대 URL로 변환."""
    url = re.sub(r'^/DRF/lawService\.do', base_url, detail_url)
    url = url.replace('type=HTML', 'type=XML')
    url = re.sub(r'&mobileYn=[^&]*', '', url)
    return url


def run(cfg: dict, ymd: str, logger: JobLogger):
    api_list_url = cfg['api_list_url']
    api_con_path = cfg['api_con_path']
    verify_ssl = (cfg['env'] != 'dev')
    csv_dir = Path(cfg['csv_path']) / ymd
    csv_dir.mkdir(parents=True, exist_ok=True)

    writer = CsvWriter('law_list', csv_dir, HEADERS, cfg['batch_size'], logger=logger)

    # api_con_path에서 base URL 한 번만 계산 (루프 안에서 반복 계산 방지)
    parsed = urlparse(api_con_path)
    con_base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    if api_list_url.endswith('='):
        base_url = f"{api_list_url}{LAW_TG}&nw=1,3"
    else:
        base_url = f"{api_list_url}&nw=1,3"
    logger.info(f'[law_list] 목록 조회 시작: {base_url}')

    # 1. 총 건수 조회
    try:
        doc = _call_api(f'{base_url}&page=1&display=100', verify_ssl)
    except Exception as exc:
        logger.error(f'[law_list] totalCnt 조회 실패: {exc}')
        writer.close()
        return
    total_cnt_el = doc.find('.//totalCnt')
    if total_cnt_el is None:
        logger.info('[law_list] totalCnt 없음 → 수집 종료')
        writer.close()
        return

    total_cnt = int(total_cnt_el.text.strip())
    total_pages = (total_cnt // 100) + 1
    logger.info(f'[law_list] totalCnt={total_cnt}, pages={total_pages}')

    # 2. 페이지 순회
    seen: set = set()
    logged_pct: set = set()
    with tqdm(total=total_pages, desc='[law_list]', unit='page') as pbar:
        for page in range(1, total_pages + 1):
            page_url = f'{base_url}&page={page}&display=100'
            try:
                page_doc = _call_api(page_url, verify_ssl)
            except Exception as e:
                logger.warning(f'[law_list] page={page} 오류: {e}')
                pbar.update(1)
                continue

            for law_el in page_doc.findall('.//law'):
                detail_url = get_list_tag_value(law_el, '법령상세링크') or ''
                detail_url = _adjust_url(detail_url, con_base_url)

                law_srno    = get_list_tag_value(law_el, '법령일련번호') or ''
                law_id      = get_list_tag_value(law_el, '법령ID') or ''
                enfc_ymd    = get_list_tag_value(law_el, '시행일자') or ''
                law_han_nm  = get_list_tag_value(law_el, '법령명한글') or ''
                prmlgt_no   = get_list_tag_value(law_el, '공포번호') or ''
                prmlgt_ymd  = get_list_tag_value(law_el, '공포일자') or ''
                entrvs_nm   = get_list_tag_value(law_el, '제개정구분명') or ''
                crnt_law_nm = get_list_tag_value(law_el, '현행연혁코드') or ''

                entrvs_cd = ENTRVS_DVS_CD_MAP.get(entrvs_nm, '')
                law_enfc_id = f'{law_srno}{enfc_ymd}'   # 법령일련번호+시행일자 (구분자 없음)

                if law_enfc_id not in seen:
                    seen.add(law_enfc_id)
                    writer.put([
                        law_enfc_id, law_srno, law_id, entrvs_cd, entrvs_nm,
                        prmlgt_ymd, prmlgt_no, law_han_nm, enfc_ymd, crnt_law_nm, detail_url,
                    ])

            pbar.update(1)
            milestone = (page * 100 // total_pages) // 10 * 10
            if milestone and milestone not in logged_pct:
                logged_pct.add(milestone)
                logger.info(f'[law_list] 진행: {page}/{total_pages}page ({milestone}%) | 수집: {writer.total_rows:,}건')

    writer.close()
    logger.info(f'[law_list] 완료 | 수집: {writer.total_rows}건 | CSV: {writer.file_count}개')
