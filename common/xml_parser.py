import re
import xml.etree.ElementTree as _ET

try:
    from lxml import etree as _lET
    def parse_xml_string(content: bytes):
        return _lET.fromstring(content)
except ImportError:
    def parse_xml_string(content: bytes):
        return _ET.fromstring(content)


def _find(element, tag):
    return element.find('.//' + tag)

def _iter_text(element):
    return ''.join(element.itertext())


def get_tag_value(root, tag: str) -> str:
    el = _find(root, tag)
    if el is None:
        return ''
    return _iter_text(el).strip()


def get_tag(element, tag_name: str) -> str:
    el = _find(element, tag_name)
    if el is None:
        return ''
    return re.sub(r'\s+', ' ', _iter_text(el)).strip()


def get_list_tag_value(element, tag: str):
    el = _find(element, tag)
    if el is None:
        return None
    return el.text


def get_tag_attr_and_value(root, tag: str, attr_name: str) -> dict:
    el = _find(root, tag)
    if el is None:
        return {'attr': '', 'text': ''}
    return {
        'attr': el.get(attr_name, ''),
        'text': (el.text or '').strip(),
    }

# v2 법령가지번호: 조번호 4자리 + 가지번호 3자리 (제2조→0002000, 제2조의2→0002002)
def make_brch_no(jo_no: str, jo_ser_no: str) -> str:
    try:
        jo = int(jo_no.strip()) if jo_no and jo_no.strip() else 0
        ser = int(jo_ser_no.strip()) if jo_ser_no and jo_ser_no.strip() else 0
    except ValueError:
        jo, ser = 0, 0
    return f'{jo:04d}{ser:03d}'


#항번호 특수기호 변환 처리 (① ~ ㊿ -> 1 ~ 50)
def convert_circled_number(s: str) -> str:
    if not s:
        return ''
    result = []
    for ch in s:
        cp = ord(ch)
        if 0x2460 <= cp <= 0x2473:
            result.append(str(cp - 0x2460 + 1))
        elif 0x3251 <= cp <= 0x325F:
            result.append(str(cp - 0x3251 + 21))
        elif 0x32B1 <= cp <= 0x32BF:
            result.append(str(cp - 0x32B1 + 36))
        else:
            result.append(ch)
    return ''.join(result).strip()
