"""HTML 법령 파싱 모듈

유럽 법령 등 HTML 형식으로 제공되는 법령을 파싱합니다.
"""
import re
import requests
from bs4 import BeautifulSoup
import pandas as pd


def parse_eu_html(url: str) -> dict:
    """유럽 법령 HTML을 파싱하여 구조화된 데이터를 반환한다.

    Args:
        url: HTML 법령 URL

    Returns:
        {
            'preamble': [{'type': 'CONSIDERING', 'text': '...'}, ...],
            'articles': [{'id': 'Article 1', 'title': '...', 'text': '...', 'hierarchy': {...}}, ...]
        }
    """
    # HTML 다운로드
    response = requests.get(url)
    response.encoding = 'utf-8'
    html = response.text

    # BeautifulSoup으로 파싱
    soup = BeautifulSoup(html, 'html.parser')

    # 전체 텍스트 추출
    text = soup.get_text()

    # 전문 파싱
    preamble = _parse_html_preamble(text)

    # 조문 파싱
    articles = _parse_html_articles(text)

    return {
        'preamble': preamble,
        'articles': articles
    }


def _parse_html_preamble(text: str) -> list[dict]:
    """HTML 텍스트에서 전문을 파싱한다."""
    # "THE CONTRACTING MEMBER STATES" 부터 "HAVE AGREED AS FOLLOWS" 까지 추출
    preamble_match = re.search(
        r'(THE CONTRACTING MEMBER STATES.*?HAVE AGREED AS FOLLOWS:)',
        text,
        re.DOTALL | re.IGNORECASE
    )

    if not preamble_match:
        return []

    preamble_text = preamble_match.group(1)

    results = []

    # 서두
    header_match = re.search(r'^(THE CONTRACTING MEMBER STATES,?)', preamble_text, re.IGNORECASE)
    if header_match:
        results.append({
            'type': '서두',
            'text': header_match.group(1).strip()
        })

    # CONSIDERING, RECALLING, WISHING 등 각 문단
    pattern = re.compile(
        r'(CONSIDERING|RECALLING|WISHING|HAVING|NOTING|DESIRING|RECOGNIZING|CONVINCED|AWARE)\s+that\s+(.*?)(?=(?:CONSIDERING|RECALLING|WISHING|HAVING|NOTING|DESIRING|RECOGNIZING|CONVINCED|AWARE)\s+that|HAVE AGREED AS FOLLOWS|$)',
        re.DOTALL | re.IGNORECASE
    )

    for match in pattern.finditer(preamble_text):
        keyword = match.group(1).upper()
        content = match.group(2).strip()
        # 끝의 세미콜론 제거
        content = re.sub(r'[;:]\s*$', '', content)
        # 줄바꿈을 공백으로 변환
        content = re.sub(r'\s+', ' ', content)

        results.append({
            'type': keyword,
            'text': f'{keyword} that {content}'
        })

    # HAVE AGREED AS FOLLOWS
    if 'HAVE AGREED AS FOLLOWS' in preamble_text:
        results.append({
            'type': '합의',
            'text': 'HAVE AGREED AS FOLLOWS:'
        })

    return results


def _parse_html_articles(text: str) -> list[dict]:
    """HTML 텍스트에서 조문을 파싱한다."""
    articles = []

    # 계층 구조 추출 (PART, CHAPTER)
    hierarchy = _extract_html_hierarchy(text)

    # Article 패턴: "Article N" + 제목 (선택)
    article_pattern = re.compile(
        r'\n(Article\s+\d+[a-z]*)\n(.*?)(?=\nArticle\s+\d+|$)',
        re.DOTALL | re.IGNORECASE
    )

    for match in article_pattern.finditer(text):
        article_id = match.group(1).strip()
        article_content = match.group(2).strip()

        # 조문 제목 추출 (첫 줄)
        lines = article_content.split('\n')
        title = ""
        content_start = 0

        if lines:
            first_line = lines[0].strip()
            # 첫 줄이 제목인지 확인 (숫자나 (a) 등으로 시작하지 않음)
            if first_line and not re.match(r'^[\d\(]', first_line):
                title = first_line
                content_start = 1

        # 본문 추출
        article_text = '\n'.join(lines[content_start:]).strip()

        # 현재 조문이 속한 계층 찾기
        article_pos = text.find(match.group(0))
        current_hierarchy = _find_hierarchy_at_position(hierarchy, article_pos)

        articles.append({
            'id': article_id,
            'title': title,
            'text': article_text,
            'hierarchy': current_hierarchy
        })

    return articles


def _extract_html_hierarchy(text: str) -> list[dict]:
    """HTML 텍스트에서 계층 구조(PART, CHAPTER 등)를 추출한다."""
    hierarchy = []

    # PART 패턴 - 더 유연하게 수정
    part_pattern = re.compile(
        r'(?:^|\n)(PART\s+[IVXLCDM]+)\s*(.*?)(?=\n\n|$)',
        re.MULTILINE
    )

    for match in part_pattern.finditer(text):
        part_num = match.group(1).strip()
        part_title_raw = match.group(2).strip()
        # 여러 줄에 걸친 제목일 수 있으므로 정리
        part_title = re.sub(r'\s+', ' ', part_title_raw).split('\n')[0]

        # CHAPTER나 Article이 아닌 경우만 제목으로 인식
        if not re.match(r'^(CHAPTER|Article)', part_title, re.IGNORECASE):
            hierarchy.append({
                'type': 'part',
                'title': f'{part_num} {part_title}'.strip() if part_title else part_num,
                'start_pos': match.start()
            })

    # CHAPTER 패턴 - 더 유연하게 수정
    chapter_pattern = re.compile(
        r'(?:^|\n)(CHAPTER\s+[IVXLCDM0-9]+)\s*(.*?)(?=\n\n|$)',
        re.MULTILINE
    )

    for match in chapter_pattern.finditer(text):
        chapter_num = match.group(1).strip()
        chapter_title_raw = match.group(2).strip()
        # 여러 줄에 걸친 제목일 수 있으므로 정리
        chapter_title = re.sub(r'\s+', ' ', chapter_title_raw).split('\n')[0]

        # Article이 아닌 경우만 제목으로 인식
        if not re.match(r'^Article', chapter_title, re.IGNORECASE):
            hierarchy.append({
                'type': 'chapter',
                'title': f'{chapter_num} {chapter_title}'.strip() if chapter_title else chapter_num,
                'start_pos': match.start()
            })

    # 위치 순서대로 정렬
    hierarchy.sort(key=lambda x: x['start_pos'])

    return hierarchy


def _find_hierarchy_at_position(hierarchy: list[dict], position: int) -> dict:
    """특정 위치에서의 계층 정보를 반환한다."""
    current_part = ""
    current_chapter = ""

    for h in hierarchy:
        if h['start_pos'] > position:
            break
        if h['type'] == 'part':
            current_part = h['title']
            current_chapter = ""  # 새 Part에서 Chapter 초기화
        elif h['type'] == 'chapter':
            current_chapter = h['title']

    return {
        'part': current_part,
        'chapter': current_chapter
    }


def parse_eu_html_to_dataframe(url: str) -> pd.DataFrame:
    """유럽 법령 HTML을 파싱하여 구조화된 DataFrame을 반환한다.

    Args:
        url: HTML 법령 URL

    Returns:
        DataFrame with columns: ['편', '장', '절', '조문번호', '조문제목', '항', '호', '목', '세목', '원문']
    """
    # HTML 파싱
    data = parse_eu_html(url)

    rows = []

    # 전문 추가
    for para in data['preamble']:
        rows.append({
            '편': '',
            '장': '',
            '절': '',
            '조문번호': '전문',
            '조문제목': para['type'],
            '항': '',
            '호': '',
            '목': '',
            '세목': '',
            '원문': para['text']
        })

    # 조문 추가
    for article in data['articles']:
        article_id = article['id']
        title = article['title']
        text = article['text']
        hierarchy = article['hierarchy']

        # 항/호 파싱 (간단 버전 - 추후 개선 가능)
        # (1), (2) 패턴으로 항 분리
        para_pattern = re.compile(r'\n\((\d+)\)\s+(.*?)(?=\n\(|$)', re.DOTALL)
        paragraphs = list(para_pattern.finditer(text))

        if not paragraphs:
            # 항이 없는 경우 전체를 하나로
            rows.append({
                '편': hierarchy['part'],
                '장': hierarchy['chapter'],
                '절': '',
                '조문번호': article_id,
                '조문제목': title,
                '항': '',
                '호': '',
                '목': '',
                '세목': '',
                '원문': text
            })
        else:
            for para_match in paragraphs:
                para_num = para_match.group(1)
                para_text = para_match.group(2).strip()

                # (a), (b) 패턴으로 호 분리
                item_pattern = re.compile(r'\n\(([a-z])\)\s+(.*?)(?=\n\(|$)', re.DOTALL)
                items = list(item_pattern.finditer(para_text))

                if not items:
                    # 호가 없는 경우
                    rows.append({
                        '편': hierarchy['part'],
                        '장': hierarchy['chapter'],
                        '절': '',
                        '조문번호': article_id,
                        '조문제목': title,
                        '항': para_num,
                        '호': '',
                        '목': '',
                        '세목': '',
                        '원문': para_text
                    })
                else:
                    for item_match in items:
                        item_letter = item_match.group(1)
                        item_text = item_match.group(2).strip()

                        rows.append({
                            '편': hierarchy['part'],
                            '장': hierarchy['chapter'],
                            '절': '',
                            '조문번호': article_id,
                            '조문제목': title,
                            '항': para_num,
                            '호': item_letter,
                            '목': '',
                            '세목': '',
                            '원문': item_text
                        })

    return pd.DataFrame(rows)


def save_structured_to_excel(df: pd.DataFrame, output_path: str):
    """구조화된 DataFrame을 엑셀로 저장한다."""
    # 엑셀에서 허용하지 않는 제어 문자 제거
    def clean_for_excel(text):
        if not isinstance(text, str):
            return text
        import re
        return re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', text)

    df_clean = df.copy()
    for col in df_clean.columns:
        if df_clean[col].dtype == 'object':
            df_clean[col] = df_clean[col].apply(clean_for_excel)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_clean.to_excel(writer, index=False, sheet_name="법조문")

        worksheet = writer.sheets["법조문"]
        for idx, col in enumerate(df_clean.columns):
            max_length = max(
                df_clean[col].astype(str).map(len).max(),
                len(col)
            )
            worksheet.column_dimensions[chr(65 + idx)].width = min(max_length + 2, 50)
