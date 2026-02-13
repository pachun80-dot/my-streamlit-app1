"""대만(중국어) 법령 파서."""

import re
from parsers.base import BaseParser, _extract_article_title


class TaiwanParser(BaseParser):
    """대만 법령 파서."""

    COUNTRY_CODE = "taiwan"
    SUPPORTED_EXTENSIONS = [".pdf"]
    PATH_KEYWORDS = ["taiwan"]
    LANG = "chinese"
    FORMAT = "standard"

    @classmethod
    def matches(cls, file_path: str) -> bool:
        import os
        path_lower = file_path.replace("\\", "/").lower()
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in cls.SUPPORTED_EXTENSIONS:
            return False
        if "taiwan" not in path_lower:
            return False
        # 중국어 파일명 확인
        filename = os.path.basename(file_path)
        if re.search(r"[\u4e00-\u9fff]", filename):
            return True
        return False

    def split_articles(self, text: str) -> list[dict]:
        return _split_chinese(text)

    def detect_hierarchy(self, text: str) -> list[dict]:
        return _detect_hierarchy_chinese(text)

    def parse_paragraphs(self, text: str) -> list[dict]:
        # 대만: 항과 호 구조가 복잡하여 전체를 하나로
        return []

    def extract_article_title(self, text: str) -> str:
        return _extract_article_title(text, "chinese")

    def find_article_position(self, article_id: str, text: str) -> int:
        if "第" in article_id and "條" in article_id:
            pattern = re.escape(article_id)
            match = re.search(pattern, text)
            if match:
                return match.start()
        return -1


def _split_chinese(text: str) -> list[dict]:
    """대만 한문(번체) 법령을 조문 단위로 분리한다.

    줄 시작에 '第N條' 가 오는 경우만 조문 시작으로 인식한다.
    """
    pattern = re.compile(
        r"(?:^|\n)"
        r"(第\s*(?:\d+|[一二三四五六七八九十百千]+)\s*條(?:\s*之\s*\d+)?)"
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
        articles.append({"id": article_id, "text": chunk})

    return articles


def _detect_hierarchy_chinese(text: str) -> list[dict]:
    """대만법에서 편/장/절 계층 구조를 감지한다."""
    hierarchy = []

    # 대만: 第一編, 第一章, 第一節
    part_pattern = re.compile(r"(?:^|\n)(第\s*[一二三四五六七八九十百]+\s*編[^\n]*)")
    chapter_pattern = re.compile(r"(?:^|\n)(第\s*[一二三四五六七八九十百]+\s*章[^\n]*)")
    section_pattern = re.compile(r"(?:^|\n)(第\s*[一二三四五六七八九十百]+\s*節[^\n]*)")

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
