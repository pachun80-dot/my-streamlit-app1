"""뉴질랜드 법령 파서."""

import re
from parsers.base import BaseParser, _extract_article_title, _clean_english_article
from parsers.epc import _parse_paragraphs_english


class NewzealandParser(BaseParser):
    """뉴질랜드 법령 파서."""

    COUNTRY_CODE = "newzealand"
    SUPPORTED_EXTENSIONS = [".pdf"]
    PATH_KEYWORDS = ["newzealand"]
    LANG = "english"
    FORMAT = "nz"

    def split_articles(self, text: str) -> list[dict]:
        return _split_nz_english(text)

    def detect_hierarchy(self, text: str) -> list[dict]:
        return _detect_hierarchy_nz(text)

    def parse_paragraphs(self, text: str) -> list[dict]:
        return _parse_paragraphs_english(text)

    def extract_article_title(self, text: str) -> str:
        return _extract_article_title(text, "english")

    def clean_article(self, article_id: str, text: str, title: str) -> str:
        return _clean_english_article(article_id, text, title)


def _split_nz_english(text: str) -> list[dict]:
    """뉴질랜드 법령을 조문 단위로 분리한다.

    뉴질랜드 법령은 조문 번호가 단독 숫자로 시작한다:
        '1 Short Title and commencement'
        '2 Interpretation'
    줄 시작에 숫자 + 제목이 오는 패턴을 매칭한다.
    """
    # 본문 영역만 추출 (목차/부칙 제거)
    part1_matches = list(re.finditer(r'\nPart\s+1\n', text))
    if len(part1_matches) >= 2:
        text = text[part1_matches[1].start():]
    elif part1_matches:
        text = text[part1_matches[0].start():]

    # 부칙(Schedule) 영역 제거
    schedule_match = re.search(r'\nSchedule\s+1AA\n', text)
    if schedule_match:
        text = text[:schedule_match.start()]
    else:
        schedule_match = re.search(r'\nSchedule\n', text)
        if schedule_match:
            text = text[:schedule_match.start()]

    # 페이지 머리글/바닥글 제거
    text = re.sub(
        r'\n\d{1,3}\nVersion as at\n[^\n]+(?:Act|Ordinance)[^\n]*',
        '', text
    )
    text = re.sub(
        r'\n[^\n]+(?:Act|Ordinance)[^\n]*\nVersion as at\n[^\n]*',
        '', text
    )

    # 수정 이력 제거
    text = re.sub(r'\nSection\s+\d+[A-Z]?\([^)]+\):[^\n]+', '', text)

    # 조문 패턴
    pattern = re.compile(
        r"(?:^|\n)"
        r"(\d+[A-Z]?)\s+"
        r"([A-Z][a-zA-Z\s,]+(?:of|for|and|in|to|the|under|with|from)?[^\n]*)"
        r"(?=\n)"
    )

    candidates = list(pattern.finditer(text))
    if not candidates:
        return [{"id": "전문", "text": text.strip()}] if text.strip() else []

    raw_articles = []
    for i, match in enumerate(candidates):
        start = match.start()
        if text[start:start + 1] == "\n":
            start += 1
        end = candidates[i + 1].start() if i + 1 < len(candidates) else len(text)
        chunk = text[start:end].strip()
        if not chunk:
            continue

        num = match.group(1)
        title = match.group(2).strip()

        if '\n' in title:
            title = title.split('\n')[0].strip()

        if len(title) < 3 or title.isdigit():
            continue
        title = re.sub(r'\s+\d{1,3}$', '', title).strip()

        if title.startswith(('Version', 'Page', 's ')):
            continue

        raw_articles.append({
            "id": num,
            "text": chunk,
            "title": title,
            "_num": int(re.match(r"\d+", num).group())
        })

    # 같은 ID 중복 시 가장 긴 본문만 유지
    seen = {}
    for a in raw_articles:
        aid = a["id"]
        if aid not in seen or len(a["text"]) > len(seen[aid]["text"]):
            seen[aid] = a

    MIN_CONTENT_LEN = 50
    filtered = {k: v for k, v in seen.items() if len(v["text"]) >= MIN_CONTENT_LEN}

    sorted_ids = sorted(filtered.keys(), key=lambda x: int(re.search(r"\d+", x).group()))

    articles = []

    if candidates:
        first_start = candidates[0].start()
        if text[first_start:first_start + 1] == "\n":
            first_start += 1
        preamble = text[:first_start].strip()
        if preamble and len(preamble) > 50:
            articles.append({"id": "전문", "text": preamble})

    for aid in sorted_ids:
        entry = filtered[aid]
        articles.append({
            "id": entry["id"],
            "text": entry["text"],
            "title": entry.get("title", "")
        })

    return articles


def _detect_hierarchy_nz(text: str) -> list[dict]:
    """뉴질랜드법에서 편/장/절 계층 구조를 감지한다."""
    hierarchy = []

    # 뉴질랜드: Part N + Subpart N—Title
    part_pattern = re.compile(r"\nPart\s+(\d+)\n([^\n]+)")
    subpart_pattern = re.compile(r"\n(Subpart\s+\d+)\s*[—\-]\s*([^\n]+)")

    for match in part_pattern.finditer(text):
        title_line = match.group(2).strip()
        if re.match(r"(s\s+\d|Page|\d)", title_line):
            continue
        part_title = f"Part {match.group(1)} {title_line}"
        hierarchy.append({
            "type": "part",
            "title": part_title,
            "start_pos": match.start()
        })

    for match in subpart_pattern.finditer(text):
        sub_title = f"{match.group(1)} {match.group(2).strip()}"
        hierarchy.append({
            "type": "chapter",
            "title": sub_title,
            "start_pos": match.start()
        })

    hierarchy.sort(key=lambda x: x["start_pos"])

    # 동일 제목 중복 제거
    seen = {}
    for h in hierarchy:
        seen[h["title"]] = h
    hierarchy = sorted(seen.values(), key=lambda x: x["start_pos"])

    return hierarchy
