"""일본 법령 HTML 파서 (v3 - HTML 구조 활용)"""

import re
import pandas as pd
from bs4 import BeautifulSoup


def parse_japan_html_to_dataframe(file_path: str) -> pd.DataFrame:
    """일본 법령 HTML 파일을 파싱하여 구조화된 DataFrame을 반환한다."""
    # HTML 파일 읽기
    with open(file_path, 'r', encoding='utf-8') as f:
        html = f.read()

    # BeautifulSoup으로 파싱
    soup = BeautifulSoup(html, 'html.parser')

    rows = []

    # Article 섹션 찾기
    articles = soup.find_all('section', class_='Article')

    # 계층 구조 추출 (章, 節) - HTML 클래스에서
    chapters = _extract_japan_chapters_from_html(soup)
    sections = _extract_japan_sections_from_html(soup)

    for article_section in articles:
        # 別表(별표) 확인 - 조문 제목에서
        caption_div = article_section.find('div', class_='_div_ArticleCaption')
        if caption_div:
            caption_text = caption_div.get_text(strip=True)
            # 別表(별표)가 나오면 종료
            if '別表' in caption_text or '別　表' in caption_text:
                break

        # 부칙 여부 확인 - 부모 섹션이 SupplProvision인지 확인
        is_fukusoku = False
        parent = article_section.parent
        while parent:
            if parent.name == 'section' and parent.get('class'):
                if 'SupplProvision' in parent.get('class'):
                    is_fukusoku = True
                    break
            parent = parent.parent

        # 조문 제목 추출 (_div_ArticleCaption)
        article_title = ''
        if caption_div:
            caption_text = caption_div.get_text(strip=True)
            # （...）에서 괄호 제거
            article_title = caption_text.strip('（）() \n')

        # 조문 번호 추출 (_div_ArticleTitle)
        title_div = article_section.find('div', class_='_div_ArticleTitle')
        if not title_div:
            continue

        title_text = title_div.get_text()

        # 조문 번호 추출
        article_match = re.search(r'第([一二三四五六七八九十百千万\d]+)条(の[一二三四五六七八九十\d]+)?', title_text)
        if not article_match:
            continue

        article_num = article_match.group(1)
        article_suffix = article_match.group(2) or ''
        article_id = f"第{article_num}条{article_suffix}"

        # 조문 내용 추출 (조문 번호 뒤의 텍스트)
        article_content = title_text[article_match.end():].strip()

        # 현재 조문이 속한 장/절 찾기 (조문 번호 범위 기반)
        # 먼저 節을 찾고, 節이 있으면 그 節의 부모 章도 함께 설정
        current_section = _find_hierarchy_by_article(article_id, sections)
        current_chapter = ''

        if current_section:
            # 節이 있으면 그 節의 부모 章을 찾기
            for s in sections:
                if s['title'] == current_section and 'parent_chapter' in s:
                    current_chapter = s['parent_chapter']
                    break

        # 節이 없거나 부모 章을 못 찾았으면 직접 章 찾기
        if not current_chapter:
            current_chapter = _find_hierarchy_by_article(article_id, chapters)

        # 항 파싱 (ParagraphSentence div들)
        para_divs = article_section.find_all('div', class_='_div_ParagraphSentence')

        # 호 파싱 (ItemSentence div들)
        item_divs = article_section.find_all('div', class_='_div_ItemSentence')

        # 조문 내용이 있고 항/호가 없는 경우
        if article_content and not para_divs and not item_divs:
            rows.append({
                '편': '附則' if is_fukusoku else '',
                '장': current_chapter,
                '절': current_section,
                '조문번호': article_id,
                '조문제목': article_title,
                '항': '1',
                '호': '',
                '목': '',
                '세목': '',
                '원문': article_content
            })
        # 1항 (첫 번째 문장) + 호들
        elif article_content:
            # 1항에 호가 있는지 확인
            first_para_items = []
            for item_div in item_divs:
                item_text_full = item_div.get_text()
                # 호 번호 추출 (一、二、三...)
                item_match = re.match(r'^([一二三四五六七八九十]+)\s+(.*)$', item_text_full.strip(), re.DOTALL)
                if item_match:
                    item_num = item_match.group(1)
                    item_text = item_match.group(2).strip()

                    # 이 호가 첫 번째 항에 속하는지 확인 (ParagraphSentence div 전에 나오면)
                    if not para_divs or (para_divs and item_div.sourceline < para_divs[0].sourceline):
                        first_para_items.append((item_num, item_text))

            if first_para_items:
                # 1항 본문 (호 제외)
                rows.append({
                    '편': '附則' if is_fukusoku else '',
                    '장': current_chapter,
                    '절': current_section,
                    '조문번호': article_id,
                    '조문제목': article_title,
                    '항': '1',
                    '호': '',
                    '목': '',
                    '세목': '',
                    '원문': article_content
                })
                # 1항의 호들
                for item_num, item_text in first_para_items:
                    rows.append({
                        '편': '附則' if is_fukusoku else '',
                        '장': current_chapter,
                        '절': current_section,
                        '조문번호': article_id,
                        '조문제목': article_title,
                        '항': '1',
                        '호': item_num,
                        '목': '',
                        '세목': '',
                        '원문': item_text
                    })
            else:
                # 호가 없으면 1항 전체
                rows.append({
                    '편': '附則' if is_fukusoku else '',
                    '장': current_chapter,
                    '절': current_section,
                    '조문번호': article_id,
                    '조문제목': article_title,
                    '항': '1',
                    '호': '',
                    '목': '',
                    '세목': '',
                    '원문': article_content
                })

        # 명시된 항들 (２、３、４...)
        for para_div in para_divs:
            para_text_full = para_div.get_text()

            # 항 번호 추출
            para_match = re.match(r'^([２３４５６７８９]|[０-９]{2})\s+(.*)$', para_text_full.strip(), re.DOTALL)
            if not para_match:
                continue

            para_num = para_match.group(1)
            para_text = para_match.group(2).strip()

            # 이 항에 속하는 호 찾기
            para_items = []
            for item_div in item_divs:
                # sourceline으로 순서 비교 (간단한 방법)
                if hasattr(item_div, 'sourceline') and hasattr(para_div, 'sourceline'):
                    # 현재 항 이후, 다음 항 이전의 호들
                    if item_div.sourceline > para_div.sourceline:
                        # 다음 항이 있으면 그 전까지
                        next_para_idx = para_divs.index(para_div) + 1
                        if next_para_idx < len(para_divs):
                            if item_div.sourceline < para_divs[next_para_idx].sourceline:
                                item_text_full = item_div.get_text()
                                item_match = re.match(r'^([一二三四五六七八九十]+)\s+(.*)$', item_text_full.strip(), re.DOTALL)
                                if item_match:
                                    para_items.append((item_match.group(1), item_match.group(2).strip()))
                        else:
                            # 마지막 항이면 이후 모든 호
                            item_text_full = item_div.get_text()
                            item_match = re.match(r'^([一二三四五六七八九十]+)\s+(.*)$', item_text_full.strip(), re.DOTALL)
                            if item_match:
                                para_items.append((item_match.group(1), item_match.group(2).strip()))

            # 항 본문
            rows.append({
                '편': '附則' if is_fukusoku else '',
                '장': current_chapter,
                '절': current_section,
                '조문번호': article_id,
                '조문제목': article_title,
                '항': para_num,
                '호': '',
                '목': '',
                '세목': '',
                '원문': para_text
            })

            # 항의 호들
            for item_num, item_text in para_items:
                rows.append({
                    '편': '附則' if is_fukusoku else '',
                    '장': current_chapter,
                    '절': current_section,
                    '조문번호': article_id,
                    '조문제목': article_title,
                    '항': para_num,
                    '호': item_num,
                    '목': '',
                    '세목': '',
                    '원문': item_text
                })

    return pd.DataFrame(rows)


def _kanji_to_arabic(kanji_num: str) -> int:
    """일본 한자 숫자를 아라비아 숫자로 변환한다."""
    if kanji_num.isdigit():
        return int(kanji_num)

    kanji_map = {
        '〇': 0, '零': 0,
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        '百': 100, '千': 1000, '万': 10000
    }

    result = 0
    temp = 0

    for char in kanji_num:
        if char in ['十', '百', '千', '万']:
            if temp == 0:
                temp = 1
            if char == '十':
                result += temp * 10
            elif char == '百':
                result += temp * 100
            elif char == '千':
                result += temp * 1000
            elif char == '万':
                result += temp * 10000
            temp = 0
        else:
            temp = kanji_map.get(char, 0)

    result += temp
    return result


def _extract_japan_chapters_from_html(soup: BeautifulSoup) -> list[dict]:
    """일본 법령 HTML 목차에서 章(장)과 조문 범위를 추출한다."""
    hierarchy = []

    # 목차에서 章 찾기 - _div_TOCChapter
    chapter_divs = soup.find_all('div', class_='_div_TOCChapter')

    for chapter_div in chapter_divs:
        # TOCChapterTitle 안의 텍스트
        title_div = chapter_div.find('div', class_='TOCChapterTitle')
        if not title_div:
            continue

        chapter_text = title_div.get_text(strip=True)

        # 第X章 패턴 파싱
        chapter_pattern = re.compile(
            r'第([一二三四五六七八九十百千万\d]+)章(?:の([一二三四五六七八九十\d]+))?\s+([^（]+)(?:（([^）]+)）)?'
        )

        match = chapter_pattern.search(chapter_text)
        if not match:
            continue

        chapter_num = match.group(1)
        chapter_suffix = match.group(2) or ''
        chapter_title = match.group(3).strip()
        article_range = match.group(4)  # 例: 第一条―第二十八条 또는 None

        full_title = f'第{chapter_num}章{("の" + chapter_suffix) if chapter_suffix else ""} {chapter_title}'

        # 조문 범위가 있으면 파싱
        if article_range:
            start_article, end_article = _parse_article_range(article_range)
            hierarchy.append({
                'title': full_title,
                'start_article': start_article,
                'end_article': end_article
            })
        else:
            # 조문 범위가 없으면 (하위 節이 있는 경우) 빈 범위로 추가
            hierarchy.append({
                'title': full_title,
                'start_article': None,
                'end_article': None
            })

    return hierarchy


def _extract_japan_sections_from_html(soup: BeautifulSoup) -> list[dict]:
    """일본 법령 HTML 목차에서 節(절)과 조문 범위를 추출한다."""
    hierarchy = []

    # 목차에서 節 찾기 - _div_TOCSection
    section_divs = soup.find_all('div', class_='_div_TOCSection')

    for section_div in section_divs:
        # TOCSectionTitle 안의 텍스트
        title_div = section_div.find('div', class_='TOCSectionTitle')
        if not title_div:
            continue

        section_text = title_div.get_text(strip=True)

        # 第X節 패턴 파싱
        section_pattern = re.compile(
            r'第([一二三四五六七八九十百千万\d]+)節\s+([^（]+)（([^）]+)）'
        )

        match = section_pattern.search(section_text)
        if not match:
            continue

        section_num = match.group(1)
        section_title = match.group(2).strip()
        article_range = match.group(3)

        # 조문 범위 파싱
        start_article, end_article = _parse_article_range(article_range)

        full_title = f'第{section_num}節 {section_title}'

        # 이 節이 속한 章 찾기 (이전 형제 div에서)
        parent_chapter = ''
        # 현재 section_div 이전의 형제들을 역순으로 확인
        prev_sibling = section_div.previous_sibling
        while prev_sibling:
            if hasattr(prev_sibling, 'name') and prev_sibling.name == 'div':
                if prev_sibling.get('class') and '_div_TOCChapter' in prev_sibling.get('class'):
                    # 이 Chapter의 제목 찾기
                    chapter_title_div = prev_sibling.find('div', class_='TOCChapterTitle')
                    if chapter_title_div:
                        chapter_text = chapter_title_div.get_text(strip=True)
                        # 괄호 제거
                        chapter_text = re.sub(r'（[^）]*）', '', chapter_text).strip()
                        parent_chapter = chapter_text
                        break
            prev_sibling = prev_sibling.previous_sibling

        hierarchy.append({
            'title': full_title,
            'start_article': start_article,
            'end_article': end_article,
            'parent_chapter': parent_chapter
        })

    return hierarchy


def _parse_article_range(range_text: str) -> tuple[str, str]:
    """조문 범위 텍스트를 파싱한다. 예: 第一条―第二十八条 → (第一条, 第二十八条)"""
    # ― 또는 ・ 로 구분
    if '―' in range_text:
        parts = range_text.split('―')
        return parts[0].strip(), parts[1].strip() if len(parts) > 1 else parts[0].strip()
    elif '・' in range_text:
        parts = range_text.split('・')
        return parts[0].strip(), parts[-1].strip()
    else:
        # 단일 조문
        return range_text.strip(), range_text.strip()


def _extract_japan_chapters(text: str) -> list[dict]:
    """일본 법령 텍스트에서 章(장)를 추출한다."""
    hierarchy = []

    chapter_pattern = re.compile(
        r'第([一二三四五六七八九十百千万\d]+)章(の[一二三四五六七八九十\d]+)?\s+([^\n（]+)',
        re.MULTILINE
    )

    for match in chapter_pattern.finditer(text):
        chapter_num = match.group(1).strip()
        chapter_suffix = match.group(2) or ''
        chapter_title = match.group(3).strip()

        chapter_title = re.sub(r'\s+', ' ', chapter_title)

        hierarchy.append({
            'title': f'第{chapter_num}章{chapter_suffix} {chapter_title}',
            'start_pos': match.start()
        })

    return hierarchy


def _extract_japan_sections(text: str) -> list[dict]:
    """일본 법령 텍스트에서 節(절)을 추출한다."""
    hierarchy = []

    section_pattern = re.compile(
        r'第([一二三四五六七八九十百千万\d]+)節\s+([^\n（]+)',
        re.MULTILINE
    )

    for match in section_pattern.finditer(text):
        section_num = match.group(1).strip()
        section_title = match.group(2).strip()

        section_title = re.sub(r'\s+', ' ', section_title)

        hierarchy.append({
            'title': f'第{section_num}節 {section_title}',
            'start_pos': match.start()
        })

    return hierarchy


def _compare_article_numbers(article1: str, article2: str) -> int:
    """두 조문 번호를 비교한다. article1 < article2이면 -1, 같으면 0, article1 > article2이면 1"""
    # 第X条 또는 第X条のY 형식 파싱
    pattern = r'第([一二三四五六七八九十百千万\d]+)条(?:の([一二三四五六七八九十\d]+))?'

    match1 = re.search(pattern, article1)
    match2 = re.search(pattern, article2)

    if not match1 or not match2:
        return 0

    # 주 조문 번호 비교
    num1 = _kanji_to_arabic(match1.group(1))
    num2 = _kanji_to_arabic(match2.group(1))

    if num1 < num2:
        return -1
    elif num1 > num2:
        return 1

    # 주 번호가 같으면 の 뒤 번호 비교
    suffix1 = match1.group(2)
    suffix2 = match2.group(2)

    if suffix1 is None and suffix2 is None:
        return 0
    elif suffix1 is None:
        return -1  # の가 없는 것이 더 앞
    elif suffix2 is None:
        return 1

    # の 뒤 번호 비교
    suffix_num1 = _kanji_to_arabic(suffix1)
    suffix_num2 = _kanji_to_arabic(suffix2)

    if suffix_num1 < suffix_num2:
        return -1
    elif suffix_num1 > suffix_num2:
        return 1
    else:
        return 0


def _find_hierarchy_by_article(article_id: str, hierarchy: list[dict]) -> str:
    """조문 번호로 해당하는 계층 정보를 찾는다."""
    for h in hierarchy:
        if 'start_article' not in h or 'end_article' not in h:
            continue

        # start_article이 None이면 스킵 (하위 節이 있는 章)
        if h['start_article'] is None or h['end_article'] is None:
            continue

        # article_id가 [start_article, end_article] 범위에 속하는지 확인
        if (_compare_article_numbers(h['start_article'], article_id) <= 0 and
            _compare_article_numbers(article_id, h['end_article']) <= 0):
            return h['title']

    return ""


def _find_hierarchy_from_element(element, hierarchy: list[dict]) -> str:
    """HTML 요소에서 계층 정보를 찾는다. (부모를 따라가면서 Chapter/Section 찾기)"""
    current = ""

    # 계층 리스트에서 element보다 앞에 나오는 것들 중 가장 마지막 것을 찾기
    for h in hierarchy:
        if 'element' not in h or h['element'] is None:
            continue

        # element가 h['element'] 이후에 나오는지 확인
        # h['element']의 모든 형제 이후 요소들을 확인
        try:
            # element가 h['element']와 같은 부모를 공유하거나 그 이후에 있으면
            h_parent = h['element'].parent
            if h_parent:
                # 같은 섹션 안에 있는지 확인
                elem_parent = element.parent
                while elem_parent:
                    if elem_parent == h_parent or h_parent in elem_parent.parents:
                        current = h['title']
                        break
                    elem_parent = elem_parent.parent
        except:
            pass

    return current


def _find_hierarchy_at_position(hierarchy: list[dict], position: int) -> str:
    """특정 위치에서의 계층 정보를 반환한다. (하위 호환용)"""
    current = ""

    for h in hierarchy:
        if h['start_pos'] > position:
            break
        current = h['title']

    return current
