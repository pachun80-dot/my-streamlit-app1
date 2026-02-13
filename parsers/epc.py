"""유럽(EPC) 법령 파서."""

import re
from parsers.base import BaseParser, _extract_article_title, _clean_english_article


class EpcParser(BaseParser):
    """유럽 특허 조약(EPC) 파서."""

    COUNTRY_CODE = "epc"
    SUPPORTED_EXTENSIONS = [".pdf"]
    PATH_KEYWORDS = ["epc", "european"]
    LANG = "english"
    FORMAT = "standard"

    @classmethod
    def matches(cls, file_path: str) -> bool:
        path_lower = file_path.replace("\\", "/").lower()
        ext = __import__('os').path.splitext(file_path)[1].lower()
        if ext not in cls.SUPPORTED_EXTENSIONS:
            return False
        for kw in cls.PATH_KEYWORDS:
            if kw in path_lower:
                return True
        return False

    def split_articles(self, text: str) -> list[dict]:
        return _split_english(text)

    def detect_hierarchy(self, text: str) -> list[dict]:
        return _detect_hierarchy_english(text)

    def parse_paragraphs(self, text: str) -> list[dict]:
        return _parse_paragraphs_english(text)

    def extract_article_title(self, text: str) -> str:
        return _extract_article_title(text, "english")

    def clean_article(self, article_id: str, text: str, title: str) -> str:
        return _clean_english_article(article_id, text, title)

    def find_article_position(self, article_id: str, text: str) -> int:
        if "Article" in article_id:
            pattern = re.escape(article_id) + r"(?:\s|$)"
            match = re.search(pattern, text)
            if match:
                return match.start()
        return -1


def _clean_epc_annotations(text: str) -> str:
    """EPC PDF의 여백 참조·개정 이력·페이지 머리글을 제거한다.

    EPC PDF는 여백에 관련 조문/규칙 참조(Art. N, R. N)가 있는데,
    텍스트 추출 시 본문에 섞여 들어온다.
    """
    # 페이지 머리글/바닥글: "숫자\nEuropean Patent Convention..."
    text = re.sub(r'\n\d{1,3}\nEuropean Patent Convention[^\n]*', '', text)
    text = re.sub(r'\nEuropean Patent Convention[^\n]*\n\d{1,3}(?=\n|$)', '', text)

    # Article/Rule 줄 끝의 여백 참조: "Article 16 Art. 15" → "Article 16"
    text = re.sub(
        r'^((?:Article|Rule)\s+\d+[A-Za-z]*)\s+(?:Art\.|R\.)\s*[\d,\s\-a-zA-Z]+$',
        r'\1', text, flags=re.MULTILINE
    )

    # 단독 여백 참조 줄: "Art. 15, 92" 또는 "R. 11, 61-65" (줄 전체)
    text = re.sub(r'(?m)^(?:Art\.|R\.)\s*[\d,\s\-a-zA-Z]{1,30}$', '', text)

    # 여백 참조 연속 줄 (줄바꿈된 참조 번호): "12d, 97, 98" 또는 "134a"
    # 숫자와 콤마가 주인 짧은 줄만 제거 (Article/Rule/Section 등은 보호)
    text = re.sub(
        r'(?m)^(?!Article|Rule|Section|The |A |An |In |No |Any )[\d][,\s\d\-a-zA-Z]{0,19}$(?=\n(?:\(|[A-Z][a-z]))',
        '', text
    )

    # 제목 줄 끝의 여백 참조: "Receiving Section R. 10, 11" → "Receiving Section"
    # "Boards of Appeal R. 12a, 12b, 12c," 처럼 알파벳 포함 참조도 처리
    # 주의: \s 대신 [ ] 사용 (개행 매칭 방지)
    text = re.sub(r'(?m)^([A-Z][a-zA-Z ]+?)[ ]+R\.[ ]*[\d, \-a-zA-Z]+[, ]*$', r'\1', text)

    # 제목 줄 끝의 참조 번호 잔여: "Legal Division 134a" → "Legal Division"
    # "Enlarged Board of Appeal 112a" → "Enlarged Board of Appeal"
    text = re.sub(r'(?m)^([A-Z][a-zA-Z ]+?)[ ]+(\d+[a-z])$', r'\1', text)

    # 본문 줄 끝의 참조 번호: "shall be responsible for: 12d, 13, 109"
    text = re.sub(r'(?m)((?:for|of|under|to):?[ ]*)(\d+[a-z]?(?:,[ ]*\d+[a-z]?)*)[ ]*$', r'\1', text)

    # "See opinion(s)/decision(s) of..." 줄 제거
    text = re.sub(r'(?m)^See opinions?(?:/decisions?)? of[^\n]*$', '', text)

    # 개정 이력 줄 제거: "Amended by...", "Inserted by...", "Title amended by..." 등
    text = re.sub(r'(?m)^(?:(?:Title )?[Aa]mended|[Ii]nserted|[Dd]eleted|See decision|See decisions) (?:by |of )[^\n]*$', '', text)

    # 연속 빈 줄 정리
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


def _split_english(text: str) -> list[dict]:
    """영문 법령을 조문 단위로 분리한다.

    줄 시작에 오는 'Article N' 만 조문 시작으로 인식한다.
    - 본문 중간의 참조("pursuant to Article 174")는 무시한다.
    - 분리 후 본문이 짧은 항목(목차·참조표 등)은 제거한다.
    - 같은 Article 번호가 여러 번 나오면 가장 긴 본문을 유지한다.
    """
    # EPC 여백 주석 제거 (European Patent Convention 포함 시)
    if "European Patent Convention" in text:
        text = _clean_epc_annotations(text)

    pattern = re.compile(
        r"(?:^|\n)"
        r"((?:Article|Section|Rule|Regulation)\s+\d+[A-Za-z]*)\b",
        re.IGNORECASE,
    )

    candidates = list(pattern.finditer(text))
    if not candidates:
        return [{"id": "전문", "text": text.strip()}] if text.strip() else []

    # 1차: 모든 줄-시작 매칭으로 분리
    raw_articles = []
    for i, match in enumerate(candidates):
        start = match.start()
        if text[start:start + 1] == "\n":
            start += 1
        end = candidates[i + 1].start() if i + 1 < len(candidates) else len(text)
        chunk = text[start:end].strip()
        if not chunk:
            continue
        article_id = match.group(1).strip()

        # 비정상 ID 필터 (PDF 줄바꿈으로 숫자가 합쳐진 경우: Article 169196 등)
        num_match = re.search(r"\d+", article_id)
        if num_match and len(num_match.group()) > 4:
            continue

        raw_articles.append({"id": article_id, "text": chunk})

    # 2차: 조문 내용에서 편/장/절 제목 제거
    hierarchy_patterns = [
        re.compile(r"^(?:PART|Part)\s+[IVX]+[^\n]*\n?", re.MULTILINE | re.IGNORECASE),
        re.compile(r"^(?:CHAPTER|Chapter)\s+[IVX0-9]+[^\n]*\n?", re.MULTILINE | re.IGNORECASE),
        re.compile(r"^(?:SECTION|Section)\s+[IVX]+[^\n]*\n?", re.MULTILINE | re.IGNORECASE),
        re.compile(r"\n(?:PART|Part)\s+[IVX]+[^\n]*", re.IGNORECASE),
        re.compile(r"\n(?:CHAPTER|Chapter)\s+[IVX0-9]+[^\n]*", re.IGNORECASE),
        re.compile(r"\n(?:SECTION|Section)\s+[IVX]+[^\n]*", re.IGNORECASE),
    ]

    for a in raw_articles:
        cleaned_text = a["text"]
        for pattern in hierarchy_patterns:
            cleaned_text = pattern.sub("", cleaned_text)
        cleaned_text = cleaned_text.strip()
        a["text"] = cleaned_text

    # 3차: 삭제 조문 감지 — 본문에 (deleted) / (repealed) 포함 시 표시
    for a in raw_articles:
        if re.search(r"\(deleted\)|\(repealed\)", a["text"], re.IGNORECASE):
            a["deleted"] = True

    # 4차: 같은 ID 중복 시 가장 긴 본문만 유지 (TOC < 본문이므로 자동 제거)
    seen = {}
    for a in raw_articles:
        aid = a["id"]
        if aid not in seen or len(a["text"]) > len(seen[aid]["text"]):
            seen[aid] = a

    # 5차: 본문이 너무 짧은 항목 제거 (단, 삭제 조문은 유지)
    MIN_CONTENT_LEN = 80
    filtered = {}
    for k, v in seen.items():
        if len(v["text"]) >= MIN_CONTENT_LEN or v.get("deleted"):
            filtered[k] = v

    # 원래 등장 순서 유지
    id_order = []
    for a in raw_articles:
        if a["id"] in filtered and a["id"] not in id_order:
            id_order.append(a["id"])
    articles = []

    # 전문(서문) 추가
    first_start = candidates[0].start()
    if text[first_start:first_start + 1] == "\n":
        first_start += 1
    preamble = text[:first_start].strip()
    if preamble:
        articles.append({"id": "전문", "text": preamble})

    for aid in id_order:
        entry = filtered[aid]
        if entry.get("deleted"):
            entry["id"] = entry["id"] + " (삭제)"
            entry["text"] = "(삭제)"
        articles.append(entry)

    return articles


def _detect_hierarchy_english(text: str) -> list[dict]:
    """영문 법령에서 편/장/절 계층 구조를 감지한다."""
    hierarchy = []

    # 영문: Part I, Chapter 1, Section 1 (전체 제목 포함)
    part_pattern = re.compile(
        r"(?:^|\n)((?:Part|PART)\s+[IVX]+)(?:\s+([A-Z][^\n]{10,70})|(\s*\n[A-Z][A-Z\s]+))?",
        re.IGNORECASE
    )
    chapter_pattern = re.compile(
        r"(?:^|\n)((?:Chapter|CHAPTER)\s+[IVX0-9]+)(?:\s+([A-Za-z][^\n]{5,60}))?",
        re.IGNORECASE
    )
    section_pattern = re.compile(
        r"(?:^|\n)((?:Section|SECTION)\s+[IVX]+)(?:\s+([A-Za-z][^\n]{5,60}))?",
        re.IGNORECASE
    )

    # 편 감지
    for match in part_pattern.finditer(text):
        part_num = match.group(1).strip()
        part_title = ""
        if match.group(2):
            part_title = match.group(2).strip()
        elif match.group(3):
            part_title = match.group(3).strip()

        if part_title:
            full_title = f"{part_num} {part_title}"
        else:
            full_title = part_num

        full_title = " ".join(full_title.split())
        full_title = re.sub(r"\s+\d+$", "", full_title)

        if "Chapter" not in full_title and "Article" not in full_title:
            hierarchy.append({
                "type": "part",
                "title": full_title,
                "start_pos": match.start()
            })

    # 장 감지
    for match in chapter_pattern.finditer(text):
        chapter_num = match.group(1).strip()
        chapter_title = match.group(2).strip() if match.group(2) else ""

        if chapter_title:
            full_title = f"{chapter_num} {chapter_title}"
        else:
            full_title = chapter_num

        full_title = " ".join(full_title.split())
        full_title = re.sub(r"\s+\d+$", "", full_title)

        if "Article" not in full_title:
            hierarchy.append({
                "type": "chapter",
                "title": full_title,
                "start_pos": match.start()
            })

    # 절 감지
    for match in section_pattern.finditer(text):
        section_num = match.group(1).strip()
        section_title = match.group(2).strip() if match.group(2) else ""

        if section_title:
            full_title = f"{section_num} {section_title}"
        else:
            full_title = section_num

        full_title = " ".join(full_title.split())
        full_title = re.sub(r"\s+\d+$", "", full_title)

        if "Article" not in full_title:
            hierarchy.append({
                "type": "section",
                "title": full_title,
                "start_pos": match.start()
            })

    # 제목 정제: <개정 ...>, <신설 ...> 등 이력 태그 제거
    for h in hierarchy:
        h["title"] = re.sub(r"\s*<[^>]+>\s*$", "", h["title"]).strip()

    # 위치 순서대로 정렬
    hierarchy.sort(key=lambda x: x["start_pos"])

    return hierarchy


def _parse_paragraphs_english(text: str) -> list[dict]:
    """영문 조문 텍스트에서 항, 호, 목을 파싱한다.

    (1), (2), (3)... (paragraph) / (a), (b), (c)... (item) / (i), (ii), (iii)... (subitem)
    """
    results = []

    # Paragraph: (1), (2)...
    para_pattern = re.compile(r"(?:^|\n)\s*\((\d+)\)\s+")
    paragraphs = list(para_pattern.finditer(text))

    if not paragraphs:
        return []

    # 정의 조항 감지
    def _is_definition_paragraph(para_text: str) -> bool:
        means_count = len(re.findall(r'\bmeans\b', para_text))
        if means_count >= 3:
            return True
        if "unless the context otherwise requires" in para_text.lower():
            return True
        return False

    for i, para_match in enumerate(paragraphs):
        para_num = para_match.group(1)
        start = para_match.end()
        end = paragraphs[i + 1].start() if i + 1 < len(paragraphs) else len(text)
        para_text = text[start:end].strip()

        # 정의 조항이면 (a)/(b) 분리 없이 전체를 하나로 유지
        if _is_definition_paragraph(para_text):
            results.append({
                "paragraph": para_num,
                "item": "",
                "subitem": "",
                "subsubitem": "",
                "text": para_text
            })
            continue

        # Item: (a), (b), (c)... (i, v, x 제외 - 로마 숫자와 구분)
        item_pattern = re.compile(r"(?:^|\n)\s*\(([a-hj-uw-z])\)\s+")
        items = list(item_pattern.finditer(para_text))

        if not items:
            results.append({
                "paragraph": para_num,
                "item": "",
                "subitem": "",
                "subsubitem": "",
                "text": para_text
            })
        else:
            # (a) 앞의 리드 텍스트를 별도 행으로 추가
            lead_text = para_text[:items[0].start()].strip()
            if lead_text:
                results.append({
                    "paragraph": para_num,
                    "item": "",
                    "subitem": "",
                    "subsubitem": "",
                    "text": lead_text
                })

            for j, item_match in enumerate(items):
                item_letter = item_match.group(1)
                item_start = item_match.end()
                item_end = items[j + 1].start() if j + 1 < len(items) else len(para_text)
                item_text = para_text[item_start:item_end].strip()

                # Subitem: (i), (ii), (iii), (iv)... (로마 숫자)
                subitem_pattern = re.compile(r"(?:^|\n)\s*\(([ivxlcdm]+)\)\s+")
                subitems = list(subitem_pattern.finditer(item_text))

                if not subitems:
                    results.append({
                        "paragraph": para_num,
                        "item": item_letter,
                        "subitem": "",
                        "subsubitem": "",
                        "text": item_text
                    })
                else:
                    for k, subitem_match in enumerate(subitems):
                        subitem_roman = subitem_match.group(1)
                        subitem_start = subitem_match.end()
                        subitem_end = subitems[k + 1].start() if k + 1 < len(subitems) else len(item_text)
                        subitem_text = item_text[subitem_start:subitem_end].strip()
                        results.append({
                            "paragraph": para_num,
                            "item": item_letter,
                            "subitem": subitem_roman,
                            "subsubitem": "",
                            "text": subitem_text
                        })

    return results
