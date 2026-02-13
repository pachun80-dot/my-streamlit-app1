"""독일 법령(XML) 파서."""

import re
import xml.etree.ElementTree as ET
from html import unescape
import pandas as pd
from parsers.base import BaseParser


class GermanyParser(BaseParser):
    """독일 법령 파서."""

    COUNTRY_CODE = "germany"
    SUPPORTED_EXTENSIONS = [".xml"]
    PATH_KEYWORDS = ["germany", "deutschland"]
    LANG = "german"
    FORMAT = "standard"

    def extract_text(self, file_path: str) -> str:
        # XML은 별도 파싱 필요
        articles = parse_german_xml(file_path)
        return "\n\n".join(a['content'] for a in articles if a.get('content'))

    def split_articles(self, text: str) -> list[dict]:
        # XML은 parse_german_xml을 직접 사용
        return []

    def detect_hierarchy(self, text: str) -> list[dict]:
        return []

    def parse_paragraphs(self, text: str) -> list[dict]:
        return []


def parse_german_xml(file_path: str) -> list[dict]:
    """독일 법령 XML 파일을 파싱하여 조문 목록을 반환한다.

    Args:
        file_path: XML 파일 경로

    Returns:
        조문 정보 딕셔너리 리스트
        각 딕셔너리는 다음 키를 포함:
        - article_num: 조문 번호 (§ 제거됨, 예: "1", "2")
        - section: 계층 구조 (예: "Erster Abschnitt")
        - section_title: 계층 제목 (예: "Das Patent")
        - content: 조문 내용 (HTML 태그 제거됨)
        - paragraphs: 항 목록 (각 항은 {'num': 번호, 'text': 내용, 'items': [호 목록]})
    """
    tree = ET.parse(file_path)
    root = tree.getroot()

    articles = []
    current_section = ""
    current_section_title = ""

    # <norm> 태그가 각 조문을 나타냄
    for norm in root.findall('.//norm'):
        # 계층 정보 추출 (Abschnitt 등)
        gliederungsbez = norm.find('.//metadaten/gliederungseinheit/gliederungsbez')
        gliederungstitel = norm.find('.//metadaten/gliederungseinheit/gliederungstitel')

        if gliederungsbez is not None and gliederungsbez.text:
            current_section = gliederungsbez.text.strip()
        if gliederungstitel is not None and gliederungstitel.text:
            current_section_title = gliederungstitel.text.strip()

        # 조문 번호 추출 (§ 1, § 2 등에서 § 제거)
        enbez = norm.find('.//metadaten/enbez')
        if enbez is None or not enbez.text:
            continue

        article_num_raw = enbez.text.strip()
        # § 기호 제거
        article_num = article_num_raw.replace('§', '').strip()

        # 조문 내용 추출
        content_elem = norm.find('.//textdaten/text/Content')
        if content_elem is None:
            continue

        # 항(Absatz) 추출 - <P> 태그
        paragraphs = []
        for p_elem in content_elem.findall('.//P'):
            # <P> 태그 내의 텍스트 추출
            p_text = _extract_text_from_element(p_elem)
            if not p_text:
                continue

            # 항 번호 추출: (1), (2), (3) 형태
            para_match = re.match(r'^\((\d+)\)\s*(.*)', p_text)
            if para_match:
                para_num = para_match.group(1)
                para_text = para_match.group(2)

                # 호 추출: "1.", "2.", "3." 형태
                items = _extract_german_items(para_text)

                paragraphs.append({
                    'num': para_num,
                    'text': para_text,
                    'items': items
                })
            else:
                # 항 번호가 없는 경우도 추가
                paragraphs.append({
                    'num': '',
                    'text': p_text,
                    'items': []
                })

        # 전체 내용도 저장
        full_content = _extract_text_from_element(content_elem)

        articles.append({
            'article_num': article_num,
            'section': current_section,
            'section_title': current_section_title,
            'content': full_content,
            'paragraphs': paragraphs
        })

    return articles


def _extract_german_items(text: str) -> list[dict]:
    """독일 법률 텍스트에서 호(item) 추출: 1., 2., 3. 형태

    날짜 패턴(예: 1. Januar, 18. August)은 제외
    """
    items = []

    # 독일어 월 이름 목록
    german_months = [
        'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
        'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'
    ]

    # "1.", "2.", "3." 등으로 시작하는 부분 찾기
    pattern = r'(\d+)\.\s*([^\n]+?)(?=\d+\.\s*[^\n]|$)'
    matches = list(re.finditer(pattern, text))

    for match in matches:
        item_num = match.group(1)
        item_text = match.group(2).strip()

        # 날짜 패턴 필터링
        is_date = False
        for month in german_months:
            if item_text.startswith(month):
                is_date = True
                break

        if not is_date and len(item_text) > 5:
            items.append({
                'num': item_num,
                'text': item_text
            })

    # 항목이 1개 이하면 실제 리스트가 아닐 가능성이 높음
    if len(items) <= 1:
        return []

    # 연속된 숫자인지 확인
    if len(items) >= 2:
        try:
            nums = [int(item['num']) for item in items]
            if nums[0] != 1 or not all(nums[i] == nums[i-1] + 1 for i in range(1, len(nums))):
                return []
        except:
            return []

    return items


def _extract_text_from_element(elem) -> str:
    """XML 요소에서 모든 텍스트를 추출하고 HTML 엔티티를 디코딩한다."""
    text_parts = []

    # 요소의 텍스트
    if elem.text:
        text_parts.append(elem.text)

    # 자식 요소들의 텍스트
    for child in elem:
        child_text = _extract_text_from_element(child)
        if child_text:
            text_parts.append(child_text)
        if child.tail:
            text_parts.append(child.tail)

    # 결합하고 HTML 엔티티 디코딩
    full_text = ''.join(text_parts)
    full_text = unescape(full_text)

    # 여러 공백을 하나로, 앞뒤 공백 제거
    full_text = re.sub(r'\s+', ' ', full_text)
    return full_text.strip()


def extract_structured_articles_from_xml(
    file_path: str,
    country: str = "독일",
    law_name: str = "특허법"
) -> pd.DataFrame:
    """독일 법령 XML을 파싱하여 구조화된 DataFrame을 반환한다.

    Args:
        file_path: XML 파일 경로
        country: 국가명 (기본값: "독일")
        law_name: 법령명 (기본값: "특허법")

    Returns:
        구조화된 DataFrame (컬럼: 국가, 편, 장, 절, 조문번호, 조문제목, 항, 호, 목, 원문)
    """
    articles = parse_german_xml(file_path)

    rows = []
    for article in articles:
        article_num = article['article_num']
        section = article['section']
        section_title = article['section_title']

        if article['paragraphs']:
            for para in article['paragraphs']:
                if para['items']:
                    for item in para['items']:
                        row = {
                            '국가': country,
                            '편': section,
                            '장': section_title,
                            '절': '',
                            '조문번호': article_num,
                            '조문제목': '',
                            '항': para['num'],
                            '호': item['num'],
                            '목': '',
                            '원문': item['text']
                        }
                        rows.append(row)
                else:
                    row = {
                        '국가': country,
                        '편': section,
                        '장': section_title,
                        '절': '',
                        '조문번호': article_num,
                        '조문제목': '',
                        '항': para['num'],
                        '호': '',
                        '목': '',
                        '원문': para['text']
                    }
                    rows.append(row)
        else:
            row = {
                '국가': country,
                '편': section,
                '장': section_title,
                '절': '',
                '조문번호': article_num,
                '조문제목': '',
                '항': '',
                '호': '',
                '목': '',
                '원문': article['content']
            }
            rows.append(row)

    return pd.DataFrame(rows)
