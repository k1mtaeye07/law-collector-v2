import hashlib
import re
import unicodedata


def fmt_elapsed(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f'{h:02d}:{m:02d}:{s:02d}'


def date_convert(ymd: str) -> str:
    """comUtil.java dateConvert() 동일 로직.
    입력: yyyyMMdd | yyyy.M.d. | yyyy.M.d | yyyyㆍMㆍd
    출력: yyyyMMdd | 미매칭 패턴 → 숫자만 추출한 문자열
    """
    if not ymd or not ymd.strip():
        return ''
    ymd = ymd.strip()
    if re.match(r'^\d{8}$', ymd):
        return ymd
    m = re.match(r'^(\d{4})[.·ㆍ](\d{1,2})[.·ㆍ](\d{1,2})[.·ㆍ]?$', ymd)
    if m:
        return f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}"
    return re.sub(r'\D', '', ymd)


# ── v2: 본문 해시 (atcl_ctxt_hsid / para_ctxt_hsid) ─────────────────────────
# !! 운영 적재 시작 후 변경 금지: 바꾸면 전 조/항이 변경으로 오탐됨 (지침 9절)
def normalize_text(s: str) -> str:
    """NFC → 연속 공백·개행을 단일 공백으로 → 앞뒤 공백 제거"""
    s = unicodedata.normalize('NFC', s or '')
    return re.sub(r'\s+', ' ', s).strip()


def ctxt_hash(s: str) -> str:
    return hashlib.sha256(normalize_text(s).encode('utf-8')).hexdigest()


# ── v2: 본문 인라인 태그 → 최신 변경일(amnd_ymd), 개정유형(amnd_typ_nm) ────────
# 예) <개정 2008.2.29, 2025.10.1>  [전문개정 2011. 4. 12.]  [본조신설 2021.6.15]  [제목개정 2018.12.11]
#     제5조 삭제 <2010. 1. 1.>  [제10조에서 이동 <2015. 1. 1.>]
_TAG_RE = re.compile(r'<([^<>]*)>|\[([^\[\]]*)\]')
_DATE_RE = re.compile(r'(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})')
_AMND_TYP_MATCH = ('전문개정', '제목개정', '신설', '삭제', '이동', '개정')  # 매칭 순서 (긴 키워드 먼저)
_AMND_TYP_PRIO = {'전문개정': 0, '신설': 1, '삭제': 2, '이동': 3, '개정': 4, '제목개정': 5}  # 같은 날짜면 작은 값 우선


def extract_amnd_info(ctxt: str) -> tuple:
    """본문 태그 중 가장 최근 날짜와 그 태그의 유형을 반환. 없으면 ('', '')"""
    best_ymd, best_typ = '', ''
    for m in _TAG_RE.finditer(ctxt or ''):
        body = m.group(1) if m.group(1) is not None else m.group(2)
        if '시행일' in body:
            continue
        dates = [f'{y}{int(mo):02d}{int(d):02d}' for y, mo, d in _DATE_RE.findall(body)]
        if not dates:
            continue
        typ = next((t for t in _AMND_TYP_MATCH if t in body), '')
        if not typ and '삭제' in ctxt[max(0, m.start() - 4):m.start()]:
            typ = '삭제'                            # "제8조 삭제 <2009.3.18>"
        if not typ:
            continue                               # 유형 없는 날짜 태그는 무시
        ymd = max(dates)
        if ymd > best_ymd or (ymd == best_ymd and _AMND_TYP_PRIO[typ] < _AMND_TYP_PRIO[best_typ]):
            best_ymd, best_typ = ymd, typ
    return best_ymd, best_typ
