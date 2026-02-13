"""미국 법령(Westlaw RTF) 파서."""

import re
from parsers.base import BaseParser, parse_rtf, _extract_article_title, _clean_english_article


class UsaParser(BaseParser):
    """미국 법령 파서."""

    COUNTRY_CODE = "usa"
    SUPPORTED_EXTENSIONS = [".rtf"]
    PATH_KEYWORDS = ["usa"]
    LANG = "english"
    FORMAT = "us"

    def extract_text(self, file_path: str) -> str:
        return parse_rtf(file_path)

    def split_articles(self, text: str) -> list[dict]:
        return _split_us_english(text)

    def detect_hierarchy(self, text: str) -> list[dict]:
        return _detect_hierarchy_us(text)

    def parse_paragraphs(self, text: str) -> list[dict]:
        return _parse_paragraphs_us(text)

    def extract_article_title(self, text: str) -> str:
        return _extract_article_title(text, "english")

    def clean_article(self, article_id: str, text: str, title: str) -> str:
        return _clean_english_article(article_id, text, title)

    def find_article_position(self, article_id: str, text: str) -> int:
        us_pat = re.compile(
            r"(?:^|\n)§\s*" + re.escape(article_id) + r"\.\s+"
        )
        all_matches = list(us_pat.finditer(text))
        if all_matches:
            return all_matches[-1].start()
        return -1


def _clean_us_westlaw_metadata(text: str) -> str:
    """Westlaw에서 다운로드한 미국법 RTF 텍스트에서 메타데이터를 제거한다."""
    text = re.sub(
        r"(?m)^CREDIT\(S\).*?(?=^§\s*\d+|\Z)",
        "", text, flags=re.DOTALL | re.MULTILINE
    )
    text = re.sub(r"(?m)^Notes of Decisions\s*\(\d+\)\s*$", "", text)
    text = re.sub(r"(?m)^End of Document\s*$", "", text)
    text = re.sub(r"(?m)^©\s*20\d{2}\s+Thomson Reuters.*$", "", text)
    text = re.sub(r"(?m)^Currentness\s*$", "", text)
    text = re.sub(r"(?m)^Effective:.*$", "", text)
    text = re.sub(r"(?m)^KeyCite\s.*$", "", text)
    text = re.sub(r"(?m)^\d+\s+U\.?S\.?C\.?A\.?\s+§\s*\d+.*$", "", text)
    text = re.sub(r"(?m)^\d+\s+USCA\s+§\s*\d+.*$", "", text)
    text = re.sub(r"(?m)^Current through P\.L\..*$", "", text)
    text = re.sub(r"(?m)^Refs & Annos\s*$", "", text)
    text = re.sub(r"(?m)^Disposition Table\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _split_us_english(text: str) -> list[dict]:
    """미국 법령(Westlaw RTF)을 조문 단위로 분리한다.

    미국법은 § N. Title 형식의 조문 패턴을 사용한다.
    예: § 101. Inventions patentable
        § 102. Conditions for patentability; novelty
    """
    text = _clean_us_westlaw_metadata(text)

    pattern = re.compile(
        r"(?:^|\n)"
        r"(§\s*\d+[a-zA-Z]?(?:-\d+[a-zA-Z]?)?)\.\s+"
        r"([^\n]+)"
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

        raw_id = match.group(1).strip()
        article_num = raw_id.replace("§", "").strip()
        title = match.group(2).strip()
        title = re.sub(r'\s+\[.*$', '', title).strip()

        raw_articles.append({
            "id": article_num,
            "text": chunk,
            "title": title
        })

    # 삭제/폐지 조문 감지
    for a in raw_articles:
        lower_text = a["text"].lower()
        if "(repealed)" in lower_text or "repealed" in a.get("title", "").lower():
            a["deleted"] = True

    # 같은 ID 중복 시 가장 긴 본문만 유지
    seen = {}
    for a in raw_articles:
        aid = a["id"]
        if aid not in seen or len(a["text"]) > len(seen[aid]["text"]):
            seen[aid] = a

    MIN_CONTENT_LEN = 60
    filtered = {}
    for k, v in seen.items():
        if len(v["text"]) >= MIN_CONTENT_LEN or v.get("deleted"):
            filtered[k] = v

    id_order = []
    for a in raw_articles:
        if a["id"] in filtered and a["id"] not in id_order:
            id_order.append(a["id"])

    articles = []

    if candidates:
        first_start = candidates[0].start()
        if text[first_start:first_start + 1] == "\n":
            first_start += 1
        preamble = text[:first_start].strip()
        if preamble and len(preamble) > 50:
            articles.append({"id": "전문", "text": preamble})

    for aid in id_order:
        entry = filtered[aid]
        if entry.get("deleted"):
            entry["id"] = entry["id"] + " (삭제)"
            entry["text"] = "(삭제)"
        articles.append(entry)

    return articles


def _detect_hierarchy_us(text: str) -> list[dict]:
    """미국법에서 편/장/절 계층 구조를 감지한다."""
    hierarchy = []

    part_pattern = re.compile(
        r"(?:^|\n)(Part\s+[IVX]+)\.?\s+([^\n]+)",
        re.IGNORECASE
    )
    chapter_pattern = re.compile(
        r"(?:^|\n)(Chapter\s+\d+)\.?\s*[—\-]?\s*([^\n]+)",
        re.IGNORECASE
    )

    for match in part_pattern.finditer(text):
        part_num = match.group(1).strip()
        part_title = match.group(2).strip()
        full_title = f"{part_num} {part_title}" if part_title else part_num
        full_title = " ".join(full_title.split())
        if "§" not in full_title:
            hierarchy.append({
                "type": "part",
                "title": full_title,
                "start_pos": match.start()
            })

    for match in chapter_pattern.finditer(text):
        ch_num = match.group(1).strip()
        ch_title = match.group(2).strip()
        full_title = f"{ch_num} {ch_title}" if ch_title else ch_num
        full_title = " ".join(full_title.split())
        if "§" not in full_title:
            hierarchy.append({
                "type": "chapter",
                "title": full_title,
                "start_pos": match.start()
            })

    # 중복 제거
    seen = {}
    for h in hierarchy:
        seen[h["title"]] = h
    hierarchy = sorted(seen.values(), key=lambda x: x["start_pos"])

    return hierarchy


def _parse_paragraphs_us(text: str) -> list[dict]:
    """미국법 조문 텍스트에서 항, 호, 목, 세목을 파싱한다.

    미국법: (a) → (1) → (A) → (i) 순서 (기존 영문 (1)→(a)→(i)와 반대)
    """
    results = []

    # 항(paragraph): (a), (b), (c) ... (i, v, x 제외 — 로마 숫자와 혼동 방지)
    para_pattern = re.compile(r"(?:^|\n)\s*\(([a-hj-uw-z])\)\s+")
    paragraphs = list(para_pattern.finditer(text))

    if not paragraphs:
        return []

    # (a) 앞의 리드 텍스트
    lead_text = text[:paragraphs[0].start()].strip()
    if lead_text:
        results.append({
            "paragraph": "",
            "item": "",
            "subitem": "",
            "subsubitem": "",
            "text": lead_text
        })

    for i, para_match in enumerate(paragraphs):
        para_letter = para_match.group(1)
        start = para_match.end()
        end = paragraphs[i + 1].start() if i + 1 < len(paragraphs) else len(text)
        para_text = text[start:end].strip()

        # 호(item): (1), (2), (3) ...
        item_pattern = re.compile(r"(?:^|\n)\s*\((\d+)\)\s+")
        items = list(item_pattern.finditer(para_text))

        if not items:
            results.append({
                "paragraph": para_letter,
                "item": "",
                "subitem": "",
                "subsubitem": "",
                "text": para_text
            })
        else:
            # (1) 앞의 리드 텍스트
            item_lead = para_text[:items[0].start()].strip()
            if item_lead:
                results.append({
                    "paragraph": para_letter,
                    "item": "",
                    "subitem": "",
                    "subsubitem": "",
                    "text": item_lead
                })

            for j, item_match in enumerate(items):
                item_num = item_match.group(1)
                item_start = item_match.end()
                item_end = items[j + 1].start() if j + 1 < len(items) else len(para_text)
                item_text = para_text[item_start:item_end].strip()

                # 목(subitem): (A), (B), (C) ...
                subitem_pattern = re.compile(r"(?:^|\n)\s*\(([A-Z])\)\s+")
                subitems = list(subitem_pattern.finditer(item_text))

                if not subitems:
                    results.append({
                        "paragraph": para_letter,
                        "item": item_num,
                        "subitem": "",
                        "subsubitem": "",
                        "text": item_text
                    })
                else:
                    for k, subitem_match in enumerate(subitems):
                        subitem_letter = subitem_match.group(1)
                        subitem_start = subitem_match.end()
                        subitem_end = subitems[k + 1].start() if k + 1 < len(subitems) else len(item_text)
                        subitem_text = item_text[subitem_start:subitem_end].strip()

                        # 세목(subsubitem): (i), (ii), (iii) ...
                        subsubitem_pattern = re.compile(r"(?:^|\n)\s*\(([ivxlcdm]+)\)\s+")
                        subsubitems = list(subsubitem_pattern.finditer(subitem_text))

                        if not subsubitems:
                            results.append({
                                "paragraph": para_letter,
                                "item": item_num,
                                "subitem": subitem_letter,
                                "subsubitem": "",
                                "text": subitem_text
                            })
                        else:
                            for l_idx, subsubitem_match in enumerate(subsubitems):
                                subsubitem_roman = subsubitem_match.group(1)
                                ss_start = subsubitem_match.end()
                                ss_end = subsubitems[l_idx + 1].start() if l_idx + 1 < len(subsubitems) else len(subitem_text)
                                ss_text = subitem_text[ss_start:ss_end].strip()
                                results.append({
                                    "paragraph": para_letter,
                                    "item": item_num,
                                    "subitem": subitem_letter,
                                    "subsubitem": subsubitem_roman,
                                    "text": ss_text
                                })

    return results
