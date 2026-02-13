"""한국 법령 파서."""

import re
from parsers.base import BaseParser, _extract_article_title


class KoreaParser(BaseParser):
    """한국 법령 파서."""

    COUNTRY_CODE = "korea"
    SUPPORTED_EXTENSIONS = [".pdf"]
    PATH_KEYWORDS = ["korea"]
    LANG = "korean"
    FORMAT = "standard"

    def split_articles(self, text: str) -> list[dict]:
        return _split_korean(text)

    def detect_hierarchy(self, text: str) -> list[dict]:
        return _detect_hierarchy_korean(text)

    def parse_paragraphs(self, text: str) -> list[dict]:
        return _parse_paragraphs_korean(text)

    def extract_article_title(self, text: str) -> str:
        return _extract_article_title(text, "korean")

    def clean_article(self, article_id: str, text: str, title: str) -> tuple[str, str, str]:
        return _clean_korean_article(article_id, text)

    def find_article_position(self, article_id: str, text: str) -> int:
        if "제" in article_id and "조" in article_id:
            pattern = re.escape(article_id) + r"(?:\(|<|\s|$)"
            match = re.search(pattern, text)
            if match:
                return match.start()
        return -1


def _split_korean(text: str) -> list[dict]:
    """한국 법령을 조문 단위로 분리한다.

    줄 시작에 '제N조' 가 오고 바로 뒤에 괄호 제목 '(목적)' 또는 '삭제' 등이
    따라오는 경우만 실제 조문 시작으로 인식한다.
    본문 중간의 참조("제55조제1항에 따른")는 무시한다.
    """
    # 줄 시작 + 제N조(의N) + 괄호제목 또는 삭제
    pattern = re.compile(
        r"(?:^|\n)"
        r"(제\s*\d+\s*조(?:의\s*\d+)?)"
        r"(?:\s*\(|삭제)"
    )
    matches = list(pattern.finditer(text))

    articles = []

    if not matches:
        return [{"id": "전문", "text": text.strip()}] if text.strip() else []

    first_start = matches[0].start()
    if text[first_start:first_start + 1] == "\n":
        first_start += 1
    preamble = text[:first_start].strip()
    if preamble:
        articles.append({"id": "전문", "text": preamble})

    for i, match in enumerate(matches):
        start = match.start()
        if text[start:start + 1] == "\n":
            start += 1
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if not chunk:
            continue

        article_id = match.group(1).strip()
        # 삭제 조문 감지
        if re.match(r"제\s*\d+\s*조(?:의\s*\d+)?\s*삭제", chunk):
            article_id = article_id + " (삭제)"
            chunk = "(삭제)"
        articles.append({"id": article_id, "text": chunk})

    return articles


def _detect_hierarchy_korean(text: str) -> list[dict]:
    """한국법에서 편/장/절 계층 구조를 감지한다."""
    hierarchy = []

    # 한국: 제1편, 제1장, 제1절
    # 편/장/절 뒤에 공백+제목이 있어야 실제 계층 제목으로 인식
    # (본문 참조 "제2장제4절을 준용한다" 등 배제)
    part_pattern = re.compile(r"(?:^|\n)(제\s*\d+\s*편(?:의\d+)?\s+[^\n]*)")
    chapter_pattern = re.compile(r"(?:^|\n)(제\s*\d+\s*장(?:의\d+)?\s+[^\n]*)")
    section_pattern = re.compile(r"(?:^|\n)(제\s*\d+\s*절(?:의\d+)?\s+[^\n]*)")

    for match in part_pattern.finditer(text):
        title = match.group(1).strip()
        hierarchy.append({"type": "part", "title": title, "start_pos": match.start()})

    for match in chapter_pattern.finditer(text):
        title = match.group(1).strip()
        hierarchy.append({"type": "chapter", "title": title, "start_pos": match.start()})

    for match in section_pattern.finditer(text):
        title = match.group(1).strip()
        hierarchy.append({"type": "section", "title": title, "start_pos": match.start()})

    # 제목 정제: <개정 ...>, <신설 ...> 등 이력 태그 제거
    for h in hierarchy:
        h["title"] = re.sub(r"\s*<[^>]+>\s*$", "", h["title"]).strip()

    # 위치 순서대로 정렬
    hierarchy.sort(key=lambda x: x["start_pos"])
    return hierarchy


def _clean_korean_article(article_id: str, article_text: str) -> tuple[str, str, str]:
    """한국법 조문에서 조문번호(숫자), 조문제목, 원문(본문)을 분리한다.

    Args:
        article_id: 원래 조문 ID (예: '제1조', '제2조의2', '제1조 (삭제)')
        article_text: 원래 조문 텍스트 (예: '제1조(목적) 이 법은...')

    Returns:
        (clean_id, title, clean_text) 튜플
        예: ('1', '목적', '이 법은...')
    """
    # 삭제 조문
    if "(삭제)" in article_id or article_text == "(삭제)":
        num_match = re.search(r"(\d+(?:의\s*\d+)?)", article_id)
        num = num_match.group(1).replace(" ", "") if num_match else article_id
        return num, "(삭제)", "(삭제)"

    # 조문번호에서 숫자 추출: 제1조 → 1, 제2조의2 → 2의2
    clean_id = article_id.replace("제", "").replace("조", "").replace(" ", "")

    # 원문에서 제N조(제목) 헤더 분리
    header_pattern = re.compile(
        r"^제\s*\d+\s*조(?:의\s*\d+)?"   # 제N조(의N)
        r"\s*"
        r"(?:\(([^)]+)\))?"               # (제목) — 선택
        r"\s*"
        r"(?:<[^>]*>\s*)*"                # <개정 ...> 태그 — 선택
    )
    match = header_pattern.match(article_text)

    title = ""
    clean_text = article_text

    if match:
        title = match.group(1) or ""
        # 제목에서 <개정...> 태그 제거
        title = re.sub(r"\s*<[^>]+>", "", title).strip()
        # 원문에서 헤더 부분 제거
        clean_text = article_text[match.end():].strip()

    # 원문이 비어있으면 원래 텍스트 유지
    if not clean_text:
        clean_text = article_text

    return clean_id, title, clean_text


def _parse_paragraphs_korean(text: str) -> list[dict]:
    """한국법 조문 텍스트에서 항, 호, 목, 세목을 파싱한다."""
    results = []

    # ① 항 패턴
    para_pattern = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]")
    paragraphs = list(para_pattern.finditer(text))

    # 항이 없는 경우 전체를 하나의 항으로 간주
    if not paragraphs:
        paragraphs_to_process = [{"num": "", "text": text}]
    else:
        paragraphs_to_process = []
        for i, para_match in enumerate(paragraphs):
            # ①②③... → 1, 2, 3... 변환
            para_num = ord(para_match.group()) - ord('①') + 1
            start = para_match.end()
            end = paragraphs[i + 1].start() if i + 1 < len(paragraphs) else len(text)
            para_text = text[start:end].strip()
            paragraphs_to_process.append({"num": str(para_num), "text": para_text})

    for para_info in paragraphs_to_process:
        para_num = para_info["num"]
        para_text = para_info["text"]

        # 호(1., 2., 3... 또는 제1호, 제2호...) 파싱
        item_pattern = re.compile(r"(?:^|\n)\s*(?:제\s*)?(\d{1,3})(?:\.\s+|호\s*)")
        items_raw = list(item_pattern.finditer(para_text))

        # 괄호 안의 "제N호" 및 참조 "제N호부터/까지/에..." 제외
        items = []
        for item in items_raw:
            start = item.start()
            end = item.end()

            # 뒤에 오는 텍스트 확인 (참조 조사 체크)
            suffix = para_text[end:min(end+10, len(para_text))]
            if re.match(r'^\s*(?:부터|까지|에|의|를|을|와|과|로|으로|이|가|는|만|도)', suffix):
                continue

            # 앞 20자 확인 (괄호 안 제외)
            prefix = para_text[max(0, start-20):start]
            if ('(' in prefix or '(' in prefix) and (')' not in prefix and ')' not in prefix):
                continue

            items.append(item)

        if not items:
            results.append({
                "paragraph": str(para_num),
                "item": "",
                "subitem": "",
                "subsubitem": "",
                "text": para_text
            })
        else:
            for j, item_match in enumerate(items):
                item_num = item_match.group(1)
                item_start = item_match.end()
                item_end = items[j + 1].start() if j + 1 < len(items) else len(para_text)
                item_text = para_text[item_start:item_end].strip()

                # 목(가., 나., 다... 또는 가목, 나목...) 파싱
                subitem_pattern = re.compile(r"(?:^|\n)\s*([가-힣])(?:\.\s+|목\s*)")
                subitems = list(subitem_pattern.finditer(item_text))

                if not subitems:
                    results.append({
                        "paragraph": str(para_num),
                        "item": item_num,
                        "subitem": "",
                        "subsubitem": "",
                        "text": item_text
                    })
                else:
                    for k, subitem_match in enumerate(subitems):
                        subitem_char = subitem_match.group(1)
                        subitem_start = subitem_match.end()
                        subitem_end = subitems[k + 1].start() if k + 1 < len(subitems) else len(item_text)
                        subitem_text = item_text[subitem_start:subitem_end].strip()

                        # 세목(1), 2), 3)... 또는 가), 나), 다)...) 파싱
                        subsubitem_pattern = re.compile(r"(?:^|\n)\s*(?:(\d{1,2})|([가-힣]))\)\s+")
                        subsubitems = list(subsubitem_pattern.finditer(subitem_text))

                        if not subsubitems:
                            results.append({
                                "paragraph": str(para_num),
                                "item": item_num,
                                "subitem": subitem_char,
                                "subsubitem": "",
                                "text": subitem_text
                            })
                        else:
                            for l, subsubitem_match in enumerate(subsubitems):
                                subsubitem_val = subsubitem_match.group(1) or subsubitem_match.group(2)
                                subsubitem_start = subsubitem_match.end()
                                subsubitem_end = subsubitems[l + 1].start() if l + 1 < len(subsubitems) else len(subitem_text)
                                subsubitem_text = subitem_text[subsubitem_start:subsubitem_end].strip()
                                results.append({
                                    "paragraph": str(para_num),
                                    "item": item_num,
                                    "subitem": subitem_char,
                                    "subsubitem": subsubitem_val,
                                    "text": subsubitem_text
                                })

    return results
