"""parsers 패키지 — 국가별 법령 파서 레지스트리 및 공개 API.

새 국가 추가 시:
1. parsers/japan.py 생성 → BaseParser 상속, @register 데코레이터
2. 아래 import 섹션에 `import parsers.japan` 추가
3. app.py의 COUNTRY_MAP에 추가
"""

import os
import re
import time
import pandas as pd

from parsers.base import (
    BaseParser,
    parse_pdf,
    parse_rtf,
    _parse_preamble,
    _extract_article_title,
    _extract_title_with_gemini,
    _clean_english_article,
    save_structured_to_excel,
)

# ══════════════════════════════════════════════════════════════
# 레지스트리
# ══════════════════════════════════════════════════════════════

_REGISTRY: list[type[BaseParser]] = []


def register(parser_cls):
    """데코레이터: 파서 클래스를 레지스트리에 등록한다."""
    _REGISTRY.append(parser_cls)
    return parser_cls


def get_parser(file_path: str) -> BaseParser:
    """파일 경로에서 적합한 파서 인스턴스를 반환한다."""
    for cls in _REGISTRY:
        if cls.matches(file_path):
            return cls()
    # 기본값: EPC 파서
    from parsers.epc import EpcParser
    return EpcParser()


# ══════════════════════════════════════════════════════════════
# 국가별 파서 등록 (import 시 자동 등록)
# ══════════════════════════════════════════════════════════════

# 각 모듈을 import하면서 @register 데코레이터로 등록
# (순환 import 방지를 위해 여기서 import)
from parsers.epc import EpcParser
from parsers.korea import KoreaParser
from parsers.taiwan import TaiwanParser
from parsers.hongkong import HongkongParser
from parsers.newzealand import NewzealandParser
from parsers.usa import UsaParser
from parsers.germany import GermanyParser

# 레지스트리에 등록 (경로 키워드가 구체적인 것 → 일반적인 것 순서)
register(KoreaParser)
register(TaiwanParser)
register(HongkongParser)
register(NewzealandParser)
register(UsaParser)
register(GermanyParser)
register(EpcParser)  # 기본 영문 파서 (맨 마지막 — fallback)


# ══════════════════════════════════════════════════════════════
# 공개 API (기존 pdf_parser.py 호환)
# ══════════════════════════════════════════════════════════════

def _detect_lang(file_path: str) -> str:
    """파일 경로와 파일명에서 언어를 자동 감지한다."""
    path_lower = file_path.replace("\\", "/").lower()
    filename = os.path.basename(file_path)

    if "korea" in path_lower:
        return "korean"

    # 대만 폴더: 파일명에 한자(CJK Unified Ideographs)가 포함되면 chinese
    if "taiwan" in path_lower:
        if re.search(r"[\u4e00-\u9fff]", filename):
            return "chinese"
        return "english"

    return "english"


def _detect_format(file_path: str) -> str:
    """파일 경로에서 법령 형식을 감지한다."""
    if file_path:
        path_lower = file_path.replace("\\", "/").lower()
        if "newzealand" in path_lower:
            return "nz"
        if "hongkong" in path_lower:
            return "hk"
        if "usa" in path_lower:
            return "us"
    return "standard"


def split_articles(text: str, lang: str = None, file_path: str = None) -> list[dict]:
    """텍스트를 조문 단위로 분리한다.

    Args:
        text: 전체 법령 텍스트
        lang: 언어 ('english', 'chinese', 'korean'). None이면 file_path로 자동 감지.
        file_path: 원본 파일 경로 (언어 자동 감지용)

    Returns:
        [{'id': '조문번호', 'text': '원문'}, ...]
    """
    if lang is None:
        lang = _detect_lang(file_path) if file_path else "english"

    if lang == "chinese":
        from parsers.taiwan import _split_chinese
        return _split_chinese(text)
    elif lang == "korean":
        from parsers.korea import _split_korean
        return _split_korean(text)

    fmt = _detect_format(file_path)
    if fmt == "nz":
        from parsers.newzealand import _split_nz_english
        return _split_nz_english(text)
    if fmt == "hk":
        from parsers.hongkong import _split_hk_english
        return _split_hk_english(text)
    if fmt == "us":
        from parsers.usa import _split_us_english
        return _split_us_english(text)

    from parsers.epc import _split_english
    return _split_english(text)


def extract_structured_articles(
    file_path: str,
    use_ai_titles: bool = False,
    gemini_api_key: str = None,
    progress_callback=None
) -> pd.DataFrame:
    """PDF에서 법조문을 계층 구조(편/장/절/조/항/호)로 추출하여 DataFrame으로 반환한다.

    Args:
        file_path: PDF 파일 경로
        use_ai_titles: True이면 AI로 제목 추출 (느리지만 정확)
        gemini_api_key: Gemini API 키 (use_ai_titles=True인 경우 필요)
        progress_callback: 진행률 콜백 함수 (current, total, message)

    Returns:
        DataFrame with columns: ['편', '장', '절', '조문번호', '조문제목', '항', '호', '목', '세목', '원문']
    """
    # 1. 텍스트 추출 (PDF 또는 RTF)
    file_ext = os.path.splitext(file_path)[1].lower()
    if file_ext == ".rtf":
        text = parse_rtf(file_path)
    else:
        text = parse_pdf(file_path)
    lang = _detect_lang(file_path)
    fmt = _detect_format(file_path)

    # 2. 계층 구조 감지 (편/장/절)
    hierarchy = _detect_hierarchy(text, lang, file_path=file_path)

    # 3. 조문 추출
    articles = split_articles(text, lang=lang, file_path=file_path)

    # 4. 각 조문의 항/호 파싱 및 DataFrame 생성
    rows = []
    current_part = ""
    current_chapter = ""
    current_section = ""

    # AI 제목 추출을 사용하는 경우 전체 조문 수 계산 (진행률 표시용)
    total_articles = len([a for a in articles if a["id"] != "전문"])
    processed_articles = 0

    for article in articles:
        article_id = article["id"]
        article_text = article["text"]

        # 전문 처리
        if article_id == "전문":
            # 전문을 문단별로 파싱
            preamble_paras = _parse_preamble(article_text)
            if preamble_paras:
                for para in preamble_paras:
                    rows.append({
                        "편": "",
                        "장": "",
                        "절": "",
                        "조문번호": "전문",
                        "조문제목": para.get("paragraph", ""),
                        "항": "",
                        "호": "",
                        "목": "",
                        "세목": "",
                        "원문": para["text"]
                    })
            else:
                rows.append({
                    "편": "",
                    "장": "",
                    "절": "",
                    "조문번호": "전문",
                    "조문제목": "",
                    "항": "",
                    "호": "",
                    "목": "",
                    "세목": "",
                    "원문": article_text
                })
            continue

        # 현재 조문이 속한 계층 정보 업데이트
        article_pos = text.find(article_text)

        # 전체 텍스트로 찾지 못한 경우 조문 ID 패턴으로 찾기
        if article_pos == -1:
            # 영문: "Article N" 형식
            if "Article" in article_id:
                pattern = re.escape(article_id) + r"(?:\s|$)"
                match = re.search(pattern, text)
                if match:
                    article_pos = match.start()
            # 한국어: "제N조" 형식
            elif "제" in article_id and "조" in article_id:
                pattern = re.escape(article_id) + r"(?:\(|<|\s|$)"
                match = re.search(pattern, text)
                if match:
                    article_pos = match.start()
            # 중국어: "第N條" 형식
            elif "第" in article_id and "條" in article_id:
                pattern = re.escape(article_id)
                match = re.search(pattern, text)
                if match:
                    article_pos = match.start()

            # 미국: "§ N." 형식
            if article_pos == -1 and fmt == "us":
                us_pat = re.compile(
                    r"(?:^|\n)§\s*" + re.escape(article_id) + r"\.\s+"
                )
                all_matches = list(us_pat.finditer(text))
                if all_matches:
                    article_pos = all_matches[-1].start()

            # 홍콩: "N." 형식
            if article_pos == -1 and fmt == "hk":
                hk_pat = re.compile(
                    r"(?:^|\n)" + re.escape(article_id) + r"\.\s+[A-Z(]"
                )
                all_matches = list(hk_pat.finditer(text))
                if all_matches:
                    article_pos = all_matches[-1].start()

            # 여전히 못 찾은 경우 처음 100자로 재시도
            if article_pos == -1 and len(article_text) > 100:
                article_pos = text.find(article_text[:100])

        latest_part = ""
        latest_chapter = ""
        latest_section = ""
        for h in hierarchy:
            if h["start_pos"] > article_pos:
                break
            if h["type"] == "part":
                latest_part = h["title"]
                latest_chapter = ""
                latest_section = ""
            elif h["type"] == "chapter":
                latest_chapter = h["title"]
                latest_section = ""
            elif h["type"] == "section":
                latest_section = h["title"]
        current_part = latest_part
        current_chapter = latest_chapter
        current_section = latest_section

        # 한국법: 조문번호/제목/원문 분리
        if lang == "korean":
            from parsers.korea import _clean_korean_article
            article_id, title, article_text = _clean_korean_article(
                article_id, article_text
            )
        else:
            # 조문 제목 추출
            if "title" in article and article["title"]:
                title = article["title"]
            elif use_ai_titles and gemini_api_key:
                title = _extract_title_with_gemini(article_text, article_id, gemini_api_key)
                time.sleep(0.5)
                processed_articles += 1
                if progress_callback:
                    progress_callback(processed_articles, total_articles, f"제목 추출 중: {article_id}")
            else:
                title = _extract_article_title(article_text, lang)

            # 영문 조문 원문 정리 (중복 헤더 제거)
            if lang in ["english", None]:
                article_text = _clean_english_article(article_id, article_text, title)

        # 항/호 파싱
        paragraphs = _parse_paragraphs_and_items(article_text, lang, fmt=fmt)

        if not paragraphs:
            rows.append({
                "편": current_part,
                "장": current_chapter,
                "절": current_section,
                "조문번호": article_id,
                "조문제목": title,
                "항": "",
                "호": "",
                "목": "",
                "세목": "",
                "원문": article_text
            })
        else:
            for para in paragraphs:
                rows.append({
                    "편": current_part,
                    "장": current_chapter,
                    "절": current_section,
                    "조문번호": article_id,
                    "조문제목": title,
                    "항": para.get("paragraph", ""),
                    "호": para.get("item", ""),
                    "목": para.get("subitem", ""),
                    "세목": para.get("subsubitem", ""),
                    "원문": para["text"]
                })

    return pd.DataFrame(rows)


def _detect_hierarchy(text: str, lang: str, file_path: str = None) -> list[dict]:
    """텍스트에서 편/장/절 계층 구조를 감지한다.

    각 국가별 파서의 detect_hierarchy를 호출한다.
    """
    fmt = _detect_format(file_path) if file_path else "standard"

    if lang == "chinese":
        from parsers.taiwan import _detect_hierarchy_chinese
        return _detect_hierarchy_chinese(text)
    elif lang == "korean":
        from parsers.korea import _detect_hierarchy_korean
        return _detect_hierarchy_korean(text)
    elif fmt == "us":
        from parsers.usa import _detect_hierarchy_us
        return _detect_hierarchy_us(text)
    elif fmt == "nz":
        from parsers.newzealand import _detect_hierarchy_nz
        return _detect_hierarchy_nz(text)
    elif fmt == "hk":
        from parsers.hongkong import _detect_hierarchy_hk
        return _detect_hierarchy_hk(text)
    else:
        from parsers.epc import _detect_hierarchy_english
        return _detect_hierarchy_english(text)


def _parse_paragraphs_and_items(text: str, lang: str, fmt: str = "standard") -> list[dict]:
    """조문 텍스트에서 항, 호, 목, 세목을 파싱한다.

    각 국가별 파서의 parse_paragraphs를 호출한다.
    """
    if fmt == "us":
        from parsers.usa import _parse_paragraphs_us
        return _parse_paragraphs_us(text)
    elif lang == "chinese":
        return []
    elif lang == "korean":
        from parsers.korea import _parse_paragraphs_korean
        return _parse_paragraphs_korean(text)
    else:
        from parsers.epc import _parse_paragraphs_english
        return _parse_paragraphs_english(text)
