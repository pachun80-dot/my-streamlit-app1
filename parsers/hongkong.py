"""홍콩 법령 파서."""

import re
from parsers.base import BaseParser, _extract_article_title, _clean_english_article
from parsers.epc import _split_english, _parse_paragraphs_english


class HongkongParser(BaseParser):
    """홍콩 법령 파서."""

    COUNTRY_CODE = "hongkong"
    SUPPORTED_EXTENSIONS = [".pdf"]
    PATH_KEYWORDS = ["hongkong"]
    LANG = "english"
    FORMAT = "hk"

    def split_articles(self, text: str) -> list[dict]:
        return _split_hk_english(text)

    def detect_hierarchy(self, text: str) -> list[dict]:
        return _detect_hierarchy_hk(text)

    def parse_paragraphs(self, text: str) -> list[dict]:
        return _parse_paragraphs_english(text)

    def extract_article_title(self, text: str) -> str:
        return _extract_article_title(text, "english")

    def clean_article(self, article_id: str, text: str, title: str) -> str:
        return _clean_english_article(article_id, text, title)

    def find_article_position(self, article_id: str, text: str) -> int:
        hk_pat = re.compile(
            r"(?:^|\n)" + re.escape(article_id) + r"\.\s+[A-Z(]"
        )
        all_matches = list(hk_pat.finditer(text))
        if all_matches:
            return all_matches[-1].start()
        return -1


def _split_hk_english(text: str) -> list[dict]:
    """홍콩 법령을 조문 단위로 분리한다.

    홍콩 법령은 조문 번호와 제목이 같은 줄에 있다:
        '14. Filing date'
        '15. Priority'

    PDF에는 목차(TOC)와 본문에 같은 패턴이 있으므로,
    같은 조문 번호가 중복될 때 가장 긴 본문을 유지한다.
    """
    # 페이지 머리글/바닥글 제거
    text = re.sub(
        r"\n(?:Patents Ordinance|Registered Designs Ordinance|Cap\.\s*\d+)[^\n]*(?:\n[^\n]{0,60}(?:Cap\.\s*\d+|Section\s+\d+)[^\n]*)*",
        "\n", text
    )
    text = re.sub(
        r"\n\s*(?:Part|Division)\s+\d+[A-Z]?\s+\d+[A-Z]?-\d+\s*(?:\n|$)",
        "\n", text
    )
    text = re.sub(
        r"\n\s*(?:Part|Division)\s+\d+[A-Z]?[—\-–].*?\d+-\d+\s*(?:\n|$)",
        "\n", text
    )
    text = re.sub(
        r"\n\s*Section\s+\d+[A-Z]*\s+Cap\.\s*\d+\s*(?:\n|$)",
        "\n", text
    )

    # 조문 패턴: 숫자. 제목 또는 숫자-숫자. 제목 (범위 조문)
    pattern = re.compile(
        r"(?:^|\n)"
        r"(\d+[A-Z]?(?:-\d+[A-Z]?)?)\.\s+"
        r"([A-Z(][^\n]+)"
        r"(?=\n|$)"
    )

    matches = list(pattern.finditer(text))

    if not matches:
        return _split_english(text)

    # 1차: 모든 매칭으로 분리
    raw_articles = []
    for i, match in enumerate(matches):
        start = match.start()
        if text[start:start + 1] == "\n":
            start += 1
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()

        # 마지막 조문에서 Schedule 영역 제거
        if i == len(matches) - 1:
            schedule_match = re.search(r'\nSchedule\s+\d+', chunk, re.IGNORECASE)
            if schedule_match:
                chunk = chunk[:schedule_match.start()].strip()

        if not chunk:
            continue

        num = match.group(1)
        title = match.group(2).strip()

        # 제목 정제
        if '\n' in title:
            title = title.split('\n')[0].strip()

        title = re.sub(r'\s+\d{1,3}-\d{1,3}$', '', title).strip()
        title = re.sub(r'\s+\d{1,3}$', '', title).strip()
        title = re.sub(r'\s+R\.\s*[\d\-,\s]*$', '', title).strip()
        title = re.sub(r'\s+Art\.\s*[\d\-,\s]*$', '', title, flags=re.IGNORECASE).strip()

        # 본문 끝에 붙은 Part/Division 헤더 블록 제거
        trail_match = re.search(
            r"\n(?:Last updated date\n[^\n]*\n)?"
            r"(?:(?:Part|Division)\s+\d+[A-Z]?[—\-–][^\n]*\n)*"
            r"(?:Part|Division)\s+\d+[A-Z]?\n"
            r"(?:[^\n]+\n)*"
            r"(?:\([^\n]+\)\n?)*"
            r"(?:(?:Part|Division)\s+\d+[A-Z]?[—\-–][^\n]*\n?)*"
            r"\s*$",
            chunk
        )
        if trail_match:
            chunk = chunk[:trail_match.start()].strip()

        # 독립 Division 헤더 제거
        chunk = re.sub(
            r"\n(?:Division)\s+\d+[A-Z]?[—\-–][^\n]+"
            r"(?:\n[a-zA-Z][^\n(][^\n]*)?"
            r"(?:\n\([^\n]+\))*"
            r"\s*$",
            "", chunk
        ).strip()

        raw_articles.append({
            "id": num,
            "text": chunk,
            "title": title
        })

    # 2차: 같은 ID 중복 시 가장 긴 본문만 유지 (목차 < 본문)
    seen = {}
    for a in raw_articles:
        aid = a["id"]
        if aid not in seen or len(a["text"]) > len(seen[aid]["text"]):
            seen[aid] = a

    # 3차: 본문이 너무 짧은 항목 제거 (목차 항목 필터링)
    MIN_CONTENT_LEN = 80
    filtered = {k: v for k, v in seen.items() if len(v["text"]) >= MIN_CONTENT_LEN}

    # 원래 등장 순서 유지
    id_order = []
    for a in raw_articles:
        if a["id"] in filtered and a["id"] not in id_order:
            id_order.append(a["id"])

    articles = []

    # 전문(서문) 추가 — 본문의 첫 조문 기준
    first_body_pos = None
    for a in raw_articles:
        if a["id"] in filtered:
            pos = text.find(a["text"])
            if first_body_pos is None or pos < first_body_pos:
                first_body_pos = pos
            break
    if first_body_pos is not None:
        preamble = text[:first_body_pos].strip()
        if preamble:
            articles.append({"id": "전문", "text": preamble})

    for aid in id_order:
        articles.append(filtered[aid])

    return articles


def _detect_hierarchy_hk(text: str) -> list[dict]:
    """홍콩법에서 편/장/절 계층 구조를 감지한다."""
    hierarchy = []

    # 홍콩: Part 1, Part 1A 또는 Part I, Part II + Division 1—Title
    part_pattern = re.compile(
        r"(?:^|\n)Part\s+(\d+[A-Z]?|[IVX]+)\n([^\n]+)",
        re.IGNORECASE,
    )
    division_pattern = re.compile(
        r"(?:^|\n)(Division\s+\d+)\s*[—\-]\s*([^\n]+)"
    )

    for match in part_pattern.finditer(text):
        title_line = match.group(2).strip()
        if re.match(r"(Cap\.|Section|Page|\d)", title_line):
            continue
        after = text[match.end():]
        for next_line in after.split("\n")[1:3]:
            nl = next_line.strip()
            if (nl and not nl.startswith("(")
                and not re.match(r"\d+[A-Z]?\.\s", nl)
                and not re.match(r"(?:Division|Part|Section)\s", nl)
                and re.search(r"\b(?:and|of|for|or|in|on|the|to|by)\s*$", title_line)):
                title_line += " " + nl
            else:
                break
        part_title = f"Part {match.group(1)} {title_line}"
        hierarchy.append({
            "type": "part",
            "title": part_title,
            "start_pos": match.start()
        })

    for match in division_pattern.finditer(text):
        title_text = match.group(2).strip()
        after = text[match.end():]
        for next_line in after.split("\n")[1:3]:
            nl = next_line.strip()
            if (nl and not nl.startswith("(")
                and not re.match(r"\d+[A-Z]?\.\s", nl)
                and not re.match(r"(?:Division|Part|Section)\s", nl)
                and re.search(r"\b(?:and|of|for|or|in|on|the|to|by)\s*$", title_text)):
                title_text += " " + nl
            else:
                break
        div_title = f"{match.group(1)} {title_text}"
        hierarchy.append({
            "type": "chapter",
            "title": div_title,
            "start_pos": match.start()
        })

    hierarchy.sort(key=lambda x: x["start_pos"])

    # 중복 제거
    seen = {}
    current_part_key = ""
    for h in hierarchy:
        m = re.match(r"((?:Part|Division)\s+\S+)", h["title"])
        base_key = m.group(1) if m else h["title"]
        if h["type"] == "part":
            current_part_key = base_key
            key = base_key
        else:
            key = f"{current_part_key}>{base_key}"
        seen[key] = h
    hierarchy = sorted(seen.values(), key=lambda x: x["start_pos"])

    return hierarchy
