"""BaseParser 클래스 및 공통 유틸리티 함수.

모든 국가별 파서는 BaseParser를 상속하며,
공통 텍스트 추출·정제 함수를 이 모듈에서 가져다 쓴다.
"""

import os
import re
import sys
import time
import subprocess
import pdfplumber
import pandas as pd
import google.generativeai as genai


# ══════════════════════════════════════════════════════════════
# BaseParser — 국가별 파서의 기본 클래스
# ══════════════════════════════════════════════════════════════

class BaseParser:
    """국가별 파서의 기본 클래스. 새 국가 추가 시 이 클래스를 상속한다."""

    COUNTRY_CODE = ""          # 예: "usa", "epc"
    SUPPORTED_EXTENSIONS = [".pdf"]  # 지원 파일 확장자
    PATH_KEYWORDS = []         # 경로 감지 키워드 예: ["usa"]
    LANG = "english"           # 기본 언어
    FORMAT = "standard"        # _detect_format 반환값

    @classmethod
    def matches(cls, file_path: str) -> bool:
        """파일 경로가 이 파서에 맞는지 판별한다."""
        path_lower = file_path.replace("\\", "/").lower()
        ext = os.path.splitext(file_path)[1].lower()

        if ext not in cls.SUPPORTED_EXTENSIONS:
            return False

        for kw in cls.PATH_KEYWORDS:
            if kw in path_lower:
                return True

        return False

    def extract_text(self, file_path: str) -> str:
        """파일에서 텍스트 추출 (PDF 기본, 서브클래스에서 RTF/XML 등 오버라이드)"""
        return parse_pdf(file_path)

    def split_articles(self, text: str) -> list[dict]:
        """텍스트를 조문 단위로 분리 (서브클래스에서 구현)"""
        return [{"id": "전문", "text": text.strip()}] if text.strip() else []

    def detect_hierarchy(self, text: str) -> list[dict]:
        """편/장/절 계층 구조 감지 (서브클래스에서 구현)"""
        return []

    def parse_paragraphs(self, text: str) -> list[dict]:
        """항/호/목/세목 파싱 (서브클래스에서 구현)"""
        return []

    def extract_article_title(self, text: str) -> str:
        """조문 제목 추출"""
        return _extract_article_title(text, self.LANG)

    def clean_article(self, article_id: str, text: str, title: str) -> str:
        """조문 원문 정리"""
        return text

    def find_article_position(self, article_id: str, text: str) -> int:
        """전체 텍스트에서 조문 위치 찾기"""
        return -1


# ══════════════════════════════════════════════════════════════
# 공통 유틸리티 함수
# ══════════════════════════════════════════════════════════════

def parse_pdf(file_path: str, filter_superscript: bool = True, use_layout: bool = True) -> str:
    """PDF 파일에서 전체 텍스트를 추출한다.

    Args:
        file_path: PDF 경로
        filter_superscript: True이면 위첨자(superscript) 문자를 제거한다.
            EPC 등 조문 번호 옆에 옛 번호가 위첨자로 붙는 PDF에 유용하다.
        use_layout: True이면 2단 구성 등 레이아웃을 고려하여 텍스트를 추출한다.
    """
    texts = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            if use_layout:
                # 2단 구성 처리: 컬럼별로 텍스트 추출
                page_text = _extract_text_with_layout(page, filter_superscript)
            elif filter_superscript and page.chars:
                page_text = _extract_without_superscript(page)
            else:
                page_text = page.extract_text()
            if page_text:
                texts.append(page_text)
    return "\n".join(texts)


def _extract_text_with_layout(page, filter_superscript: bool = True) -> str:
    """2단 구성 등 레이아웃을 고려하여 텍스트를 추출한다.

    페이지를 좌우로 나누어 왼쪽 컬럼을 먼저 읽고, 오른쪽 컬럼을 읽는다.
    단어가 잘리지 않도록 layout=True 옵션을 사용한다.
    """
    if not page.chars:
        return page.extract_text() or ""

    # 페이지 너비의 중간점 계산
    page_width = page.width
    page_height = page.height
    mid_x = page_width / 2

    # 문자들의 x 좌표 분포를 확인하여 2단 구성인지 판단
    x_coords = [c["x0"] for c in page.chars]
    left_chars = sum(1 for x in x_coords if x < mid_x)
    right_chars = sum(1 for x in x_coords if x >= mid_x)

    # 양쪽에 문자가 골고루 분포되어 있으면 2단 구성으로 판단
    # (왼쪽/오른쪽 각각 전체의 30% 이상)
    total_chars = len(x_coords)
    is_two_column = (
        total_chars > 0 and
        left_chars / total_chars > 0.3 and
        right_chars / total_chars > 0.3
    )

    if is_two_column:
        # 2단 구성: 왼쪽 컬럼과 오른쪽 컬럼을 별도로 추출
        # 실제 컬럼 경계 찾기 (중간 공백 영역)
        # x 좌표를 정렬하여 가장 큰 간격 찾기
        sorted_x = sorted(set([c["x0"] for c in page.chars]))
        max_gap = 0
        gap_pos = mid_x

        for i in range(len(sorted_x) - 1):
            gap = sorted_x[i + 1] - sorted_x[i]
            # mid_x 근처(±20%)에서 가장 큰 간격 찾기
            if (abs(sorted_x[i] - mid_x) < page_width * 0.2 and gap > max_gap):
                max_gap = gap
                gap_pos = (sorted_x[i] + sorted_x[i + 1]) / 2

        # 찾은 간격이 충분히 크면 사용, 아니면 mid_x 사용
        if max_gap > page_width * 0.05:
            mid_x = gap_pos

        # 왼쪽 컬럼 (0 ~ mid_x)
        left_bbox = (0, 0, mid_x, page_height)
        left_crop = page.crop(left_bbox)

        # 오른쪽 컬럼 (mid_x ~ page_width)
        right_bbox = (mid_x, 0, page_width, page_height)
        right_crop = page.crop(right_bbox)

        # 각 컬럼에서 텍스트 추출 (layout=True로 단어 보존)
        if filter_superscript:
            left_text = _extract_without_superscript(left_crop)
            right_text = _extract_without_superscript(right_crop)
        else:
            # layout=True 옵션으로 단어가 잘리지 않도록 함
            left_text = left_crop.extract_text(layout=True) or ""
            right_text = right_crop.extract_text(layout=True) or ""

        # 왼쪽 컬럼 먼저, 그 다음 오른쪽 컬럼
        return left_text + "\n" + right_text
    else:
        # 단일 컬럼: 일반 추출
        if filter_superscript:
            return _extract_without_superscript(page)
        else:
            return page.extract_text(layout=True) or ""


def _extract_without_superscript(page) -> str:
    """위첨자 문자를 제거한 텍스트를 추출한다."""
    chars = page.chars
    if not chars:
        return page.extract_text(layout=True) or ""

    # 페이지 내 주요 폰트 크기 판별 (최빈값)
    from collections import Counter
    sizes = [round(c["size"], 1) for c in chars]
    if not sizes:
        return page.extract_text(layout=True) or ""
    dominant_size = Counter(sizes).most_common(1)[0][0]

    # 주요 크기의 75% 미만인 문자는 위첨자로 간주하여 제거
    threshold = dominant_size * 0.75
    filtered = [c for c in chars if c["size"] >= threshold]

    # 필터링된 문자로 텍스트 재구성 (pdfplumber의 기본 extract_text 로직 활용)
    if not filtered:
        return page.extract_text(layout=True) or ""

    # 필터링된 chars만으로 페이지 텍스트 재추출
    filtered_page = page.filter(
        lambda obj: obj.get("size", 999) >= threshold
        if obj["object_type"] == "char"
        else True
    )
    return filtered_page.extract_text(layout=True) or ""


def parse_rtf(file_path: str) -> str:
    """RTF 파일에서 텍스트를 추출한다.

    macOS에서는 textutil 명령을 사용하고,
    그 외에는 striprtf 라이브러리를 사용한다.
    최종 fallback으로 RTF 태그를 regex로 제거한다.
    """
    # macOS: textutil 사용
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["textutil", "-convert", "txt", "-stdout", file_path],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # fallback 1: striprtf 라이브러리
    try:
        from striprtf.striprtf import rtf_to_text
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            rtf_content = f.read()
        return rtf_to_text(rtf_content)
    except ImportError:
        pass

    # fallback 2: regex로 RTF 태그 제거
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        rtf_content = f.read()

    # RTF 제어 문자 제거
    text = re.sub(r'\\[a-z]+\d*\s?', '', rtf_content)
    text = re.sub(r'[{}]', '', text)
    text = re.sub(r'\\\'[0-9a-fA-F]{2}', '', text)
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _parse_preamble(preamble_text: str) -> list[dict]:
    """전문(preamble)을 문단별로 파싱한다.

    전문은 일반적으로 다음 패턴으로 구성됨:
    - "THE CONTRACTING MEMBER STATES,"
    - "CONSIDERING that...", "RECALLING that...", "WISHING to..." 등
    - "HAVE AGREED AS FOLLOWS:"

    Returns:
        [{"paragraph": "1", "text": "CONSIDERING that..."}, ...]
    """
    if not preamble_text or len(preamble_text.strip()) < 20:
        return []

    results = []

    # 전문 패턴: CONSIDERING, RECALLING, WISHING, HAVING 등으로 시작하는 문단
    # 각 문단은 대문자 키워드로 시작하고 세미콜론 또는 콜론으로 끝남
    preamble_pattern = re.compile(
        r'\b(CONSIDERING|RECALLING|WISHING|HAVING|NOTING|DESIRING|RECOGNIZING|CONVINCED|AWARE)\s+',
        re.IGNORECASE
    )

    # "THE CONTRACTING MEMBER STATES," 등 서두 추출
    header_match = re.search(
        r'^(THE\s+CONTRACTING\s+MEMBER\s+STATES,?|THE\s+PARTIES,?)',
        preamble_text,
        re.IGNORECASE | re.MULTILINE
    )
    if header_match:
        results.append({
            "paragraph": "서두",
            "text": header_match.group(0).strip()
        })

    # 각 문단 추출
    matches = list(preamble_pattern.finditer(preamble_text))
    for i, match in enumerate(matches):
        keyword = match.group(1).upper()
        start = match.start()
        # 다음 패턴까지 또는 "HAVE AGREED" 까지
        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            # "HAVE AGREED" 찾기
            agreed_match = re.search(r'\bHAVE\s+AGREED\s+AS\s+FOLLOWS:', preamble_text[start:])
            if agreed_match:
                end = start + agreed_match.start()
            else:
                end = len(preamble_text)

        para_text = preamble_text[start:end].strip()
        # 끝의 세미콜론 제거
        para_text = re.sub(r'[;:]\s*$', '', para_text)

        if para_text:
            results.append({
                "paragraph": keyword,
                "text": para_text
            })

    # "HAVE AGREED AS FOLLOWS:" 추가
    agreed_match = re.search(r'\b(HAVE\s+AGREED\s+AS\s+FOLLOWS:?)', preamble_text, re.IGNORECASE)
    if agreed_match:
        results.append({
            "paragraph": "합의",
            "text": agreed_match.group(1).strip()
        })

    return results


def _extract_article_title(text: str, lang: str) -> str:
    """조문 텍스트에서 제목을 추출한다."""
    if lang == "chinese":
        # 第N條 (제목)
        match = re.match(r"第\s*(?:\d+|[一二三四五六七八九十百千]+)\s*條(?:\s*之\s*\d+)?\s*\(([^)]+)\)", text)
        if match:
            return match.group(1)
    elif lang == "korean":
        # 제N조(제목)
        match = re.match(r"제\s*\d+\s*조(?:의\s*\d+)?\s*\(([^)]+)\)", text)
        if match:
            return match.group(1)
    else:
        # 영문: 제목은 보통 2번째 줄에 있음
        lines = text.split('\n')
        if len(lines) < 2:
            return ""

        # 2번째 줄을 제목으로 시도
        title_line = lines[1].strip()

        # 빈 줄이면 제외
        if not title_line:
            return ""

        # 제목 정제
        # 1. 참조 번호 제거
        # "R. 39", "R. 9-13", "R." 등 (끝에 있는 경우)
        title_line = re.sub(r'\s+R\.(\s*[\d\-,\s]*)?$', '', title_line)
        # 중간의 R. 참조도 제거
        title_line = re.sub(r'\s+R\.\s*[\d\-,\s]+', '', title_line)

        # 2. "Art. X" 참조 제거
        title_line = re.sub(r'\s+Art\.\s*[\d\-,\s]+', '', title_line, flags=re.IGNORECASE)

        # 3. 끝의 숫자 나열 제거 "70, 99-105c, 142" 또는 "70, 99-105c,"
        title_line = re.sub(r'\s+\d+[\-,\s\da-z]*$', '', title_line)

        # 4. 끝의 페이지 번호 제거 (숫자 1-3개만)
        title_line = re.sub(r'\s+\d{1,3}$', '', title_line)

        title_line = title_line.strip()

        # 제목 검증
        # 1. 너무 짧으면 제외
        if len(title_line) < 3:
            return ""

        # 2. 괄호로 시작하면 본문이므로 제외 "(1)", "(a)" 등
        if title_line.startswith('('):
            return ""

        # 3. 숫자로만 이루어진 경우 제외
        if title_line.isdigit():
            return ""

        # 4. 숫자나 특수문자가 너무 많으면 제외
        alpha_count = sum(c.isalpha() or c.isspace() for c in title_line)
        if len(title_line) > 0 and alpha_count / len(title_line) < 0.5:
            return ""

        # 너무 길면 첫 100자만
        if len(title_line) > 100:
            title_line = title_line[:100] + "..."

        return title_line

    return ""


def _extract_title_with_gemini(article_text: str, article_id: str, gemini_api_key: str) -> str:
    """Gemini API를 사용하여 법조문에서 제목을 추출한다.

    Args:
        article_text: 조문 원문
        article_id: 조문 번호 (예: "Article 1")
        gemini_api_key: Gemini API 키

    Returns:
        추출된 제목. 제목이 없으면 빈 문자열.
    """
    if not gemini_api_key or gemini_api_key == "your-key-here":
        return ""

    # 텍스트가 너무 길면 처음 500자만 사용
    text_sample = article_text[:500] if len(article_text) > 500 else article_text

    prompt = f"""다음은 법조문의 일부입니다. 이 조문의 제목만 추출하세요.

조문 번호: {article_id}
조문 내용:
{text_sample}

규칙:
1. 조문에 제목이 있으면 제목만 반환
2. 제목이 없으면 빈 문자열 반환 (아무것도 출력하지 마세요)
3. 조문 참조는 제목이 아닙니다 (예: "Article 24", "under Article X", "R. 39" 등)
4. 순수한 제목만 추출 (참조 번호 제외)
5. 제목은 보통 2-10단어 정도입니다

제목:"""

    try:
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel(
            "gemini-2.5-flash",
            system_instruction="당신은 법률 문서 전문가입니다. 법조문에서 제목을 정확하게 추출합니다.",
        )

        response = model.generate_content(
            prompt,
            request_options={"timeout": 30},
        )

        # 응답이 차단되었거나 빈 경우 안전하게 처리
        if not response.candidates:
            return ""
        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            return ""
        title = candidate.content.parts[0].text.strip()

        # 응답 검증
        # 1. 너무 길면 제목이 아님 (100자 이상)
        if len(title) > 100:
            return ""

        # 2. 조문 번호가 포함되어 있으면 제목이 아님
        if re.search(r'\bArticle\s+\d+|\bSection\s+\d+|\bArt\.\s*\d+', title, re.IGNORECASE):
            return ""

        # 3. "제목 없음", "없음", "no title" 등의 응답은 빈 문자열로
        if re.search(r'(no title|없음|제목\s*없음|none)', title, re.IGNORECASE):
            return ""

        return title

    except Exception as e:
        # API 오류 시 빈 문자열 반환
        print(f"Warning: Gemini API error for {article_id}: {type(e).__name__}")
        return ""


def _clean_english_article(article_id: str, article_text: str, article_title: str = "") -> str:
    """영문 조문에서 중복 헤더를 제거한다.

    Args:
        article_id: 조문 ID (예: 'Article 3', 'Article 4a')
        article_text: 원문 텍스트
        article_title: 이미 추출된 조문 제목 (선택)

    Returns:
        정리된 원문 (헤더 제거)

    Example:
        Input: "Article 3 Art. 79, 149\nTerritorial effect R. 39\nThe grant..."
        Output: "The grant..."
    """
    lines = article_text.split("\n")
    clean_lines = []
    skip_lines = 0

    for i, line in enumerate(lines):
        line_stripped = line.strip()

        # 첫 번째 줄: Article N 형식 제거
        if i == 0 and article_id in line_stripped:
            skip_lines += 1
            continue

        # 초반 몇 줄: 제목이나 참조번호 포함 시 제거
        if i < 3:
            # 참조번호 패턴 (Art. 79, 149 / R. 39 등)
            if re.match(r"^(?:Art\.|R\.|Rule|Reg\.)\s*[\d,\s-]+$", line_stripped, re.IGNORECASE):
                skip_lines += 1
                continue

            # 제목 줄 (정확히 일치하면 제거)
            if article_title and line_stripped == article_title:
                skip_lines += 1
                continue

            # 제목이 여러 단어로 구성된 경우 부분 매칭
            # 단, 라인이 제목보다 훨씬 길면 (150% 초과) 실제 내용으로 간주
            if article_title and len(line_stripped) < 100 and len(line_stripped) <= len(article_title) * 1.5:
                # 제목 단어가 80% 이상 일치하고 길이가 비슷하면 제목 줄로 간주
                title_words = set(article_title.lower().split())
                line_words = set(line_stripped.lower().split())
                if title_words and len(title_words & line_words) / len(title_words) > 0.8:
                    skip_lines += 1
                    continue

        # 실제 내용 시작 (문장 형태)
        if line_stripped and (len(line_stripped) > 20 or i >= 3):
            clean_lines.append(line)

    clean_text = "\n".join(clean_lines).strip()

    # 정리 후에도 내용이 없으면 원본 반환
    if not clean_text or len(clean_text) < 10:
        return article_text

    return clean_text


def save_structured_to_excel(df: pd.DataFrame, output_path: str):
    """구조화된 법조문 DataFrame을 엑셀로 저장한다."""
    # 엑셀에서 허용하지 않는 제어 문자 제거
    def clean_for_excel(text):
        if not isinstance(text, str):
            return text
        # 제어 문자 제거 (탭, 줄바꿈 제외)
        return re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', text)

    # 모든 문자열 컬럼에 대해 정제
    df_clean = df.copy()
    for col in df_clean.columns:
        if df_clean[col].dtype == 'object':
            df_clean[col] = df_clean[col].apply(clean_for_excel)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_clean.to_excel(writer, index=False, sheet_name="법조문")

        # 컬럼 너비 자동 조정
        worksheet = writer.sheets["법조문"]
        for idx, col in enumerate(df_clean.columns):
            max_length = max(
                df_clean[col].astype(str).map(len).max(),
                len(col)
            )
            worksheet.column_dimensions[chr(65 + idx)].width = min(max_length + 2, 50)
