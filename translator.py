import re
import time
import os
import warnings
import streamlit as st

# gRPC 및 Gemini 경고 억제
os.environ['GRPC_ENABLE_FORK_SUPPORT'] = '0'
os.environ['GRPC_POLL_STRATEGY'] = 'poll'
warnings.filterwarnings('ignore', category=FutureWarning)

import google.generativeai as genai
import anthropic


# AI 사고 과정 누출 패턴
_THINKING_MARKERS = [
    "번역 과정:", "번역 과정 :", "번역 대상 텍스트:", "번역 대상 텍스트 :",
    "분석:", "분석 :", "사용자에게서", "번역 결과:",
    "번역 결과 :", "번역문:", "번역문 :",
    "원문:", "원문 :", "해석:", "해석 :",
    "초벌 번역", "최종 검토", "최종안:", "최종안 :",
    "직역 위주", "법률 용어",
]


def _clean_translation_output(text: str) -> str:
    """AI 사고 과정 누출을 제거하고 번역문만 추출한다."""
    if not text or text.startswith("["):
        return text

    # 마크다운 사고 과정 감지: "**" 또는 "* "로 시작하고 "최종안:" 등이 포함된 경우
    # → "최종안:" 이후 번역문만 추출
    if text.lstrip().startswith(("**", "* ")) or "최종안:" in text or "최종안 :" in text:
        for final_marker in ["최종안:", "최종안 :"]:
            final_idx = text.rfind(final_marker)
            if final_idx != -1:
                after = text[final_idx + len(final_marker):].strip()
                # 마크다운 서식 제거
                after = re.sub(r'\*\*([^*]+)\*\*', r'\1', after)
                after = re.sub(r'^\s*\*\s+', '', after, flags=re.MULTILINE)
                after = after.strip()
                # 번역문 다음에 오는 해설/분석 제거: 첫 번째 빈 줄 또는 분석 패턴에서 자름
                cut_patterns = [
                    "\n    이것이", "\n    여기서", "\n    조금",
                    "\n    마지막으로", "\n    전체적으로",
                    "\n이것이", "\n여기서",
                ]
                for cp in cut_patterns:
                    cp_idx = after.find(cp)
                    if cp_idx > 0:
                        after = after[:cp_idx].strip()
                if after:
                    return after

    # 사고 과정 마커가 있는지 확인
    for marker in _THINKING_MARKERS:
        idx = text.find(marker)
        if idx == -1:
            continue

        # 마커가 텍스트 맨 앞에 있는 경우: 마커 이후의 내용이 번역문
        if idx < 20:
            after = text[idx + len(marker):].strip()
            # 다른 마커가 또 있으면 재귀 정리
            cleaned = _clean_translation_output(after)
            if cleaned and not any(m in cleaned[:30] for m in _THINKING_MARKERS):
                return cleaned
        else:
            # 마커가 중간/끝에 있는 경우: 마커 이전이 번역문
            before = text[:idx].strip()
            if before:
                return before

    # 마크다운 볼드/리스트 서식이 과도한 경우 (사고 과정 가능성)
    lines = text.strip().split('\n')
    md_lines = sum(1 for l in lines if l.strip().startswith(('**', '* ', '- ')))
    if len(lines) > 3 and md_lines / len(lines) > 0.5:
        # 마크다운이 아닌 일반 텍스트 줄만 추출
        plain = [l for l in lines if not l.strip().startswith(('**', '* ', '- ', '#'))]
        if plain:
            return '\n'.join(plain).strip()

    return text


def _get_system_prompt(source_lang: str) -> str:
    """소스 언어에 맞는 시스템 프롬프트를 반환한다."""
    number_instruction = (
        "원문의 항 번호 체계((1), (2), (a), (b) 등)를 그대로 유지하여 번역하십시오. "
    )
    output_instruction = (
        "번역문만 출력하십시오. 설명, 분석, 사고 과정 등은 절대 포함하지 마십시오."
    )
    if source_lang == "chinese":
        return (
            "당신은 전문 한문-한글 법률 번역가입니다. "
            "대만 번체 한문으로 작성된 법령 조문을 정확하고 자연스러운 한국어로 번역하십시오. "
            "법률 용어의 정확성을 최우선으로 하되, 한국 법률 용어 관례에 맞게 번역하십시오. "
            + number_instruction + output_instruction
        )
    return (
        "당신은 전문 영문-한글 법률 번역가입니다. "
        "영문으로 작성된 법령 조문을 정확하고 자연스러운 한국어로 번역하십시오. "
        "법률 용어의 정확성을 최우선으로 하되, 한국 법률 용어 관례에 맞게 번역하십시오. "
        + number_instruction + output_instruction
    )


def _get_diff_prompt() -> str:
    """두 번역문 비교 요약용 시스템 프롬프트를 반환한다."""
    return (
        "당신은 법률 번역 비교 전문가입니다. "
        "두 가지 번역문의 핵심 해석 차이를 한국어 1문장으로 간결하게 요약하십시오. "
        "차이가 없으면 '실질적 차이 없음'이라고 답하십시오."
    )


MAX_RETRIES = 3


def _call_gemini_with_retry(text: str, system_prompt: str) -> str:
    """Gemini API를 재시도 포함하여 호출한다."""
    api_key = st.secrets.get("GEMINI_API_KEY", "")
    if not api_key or api_key == "your-key-here":
        return ""

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        system_instruction=system_prompt,
    )

    for attempt in range(MAX_RETRIES):
        try:
            response = model.generate_content(
                text,
                request_options={"timeout": 120},
            )
            # 응답이 차단되었거나 빈 경우 안전하게 처리
            if not response.candidates:
                return "[Gemini 응답 없음]"
            candidate = response.candidates[0]
            if not candidate.content or not candidate.content.parts:
                return "[Gemini 응답 없음]"
            raw = candidate.content.parts[0].text.strip()
            return _clean_translation_output(raw)
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = 3 * (attempt + 1)
                time.sleep(wait)
            else:
                error_name = type(e).__name__
                if "ResourceExhausted" in error_name or "429" in str(e):
                    return "[Gemini 오류: API 할당량 초과 - 잠시 후 재시도]"
                return f"[Gemini 오류: {error_name}]"


def translate_gemini(text: str, system_prompt: str) -> str:
    """Gemini API로 번역한다."""
    api_key = st.secrets.get("GEMINI_API_KEY", "")
    if not api_key or api_key == "your-key-here":
        return "[Gemini API 키 미설정]"
    result = _call_gemini_with_retry(text, system_prompt)
    return result if result else "[Gemini 번역 실패]"


def translate_claude(text: str, system_prompt: str) -> str:
    """Claude API로 번역한다."""
    api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    if not api_key or api_key == "your-key-here":
        return "[Claude API 키 미설정]"

    for attempt in range(MAX_RETRIES):
        try:
            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=8192,
                system=system_prompt,
                messages=[{"role": "user", "content": text}],
            )
            raw = message.content[0].text.strip()
            return _clean_translation_output(raw)
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = 3 * (attempt + 1)
                time.sleep(wait)
            else:
                error_name = type(e).__name__
                error_msg = str(e)[:200]
                return f"[Claude 오류: {error_name} — {error_msg}]"


def summarize_diff(gemini_result: str, claude_result: str) -> str:
    """두 번역문의 해석 차이를 1문장으로 요약한다."""
    if gemini_result.startswith("[") or claude_result.startswith("["):
        return "비교 불가 (API 오류)"

    prompt = (
        f"번역문 A (Gemini):\n{gemini_result}\n\n"
        f"번역문 B (Claude):\n{claude_result}\n\n"
        "위 두 법률 번역문의 핵심 해석 차이를 한국어 1문장으로 요약하십시오."
    )

    result = _call_gemini_with_retry(prompt, _get_diff_prompt())
    return result if result else "비교 불가 (타임아웃)"


def translate_batch(
    articles: list[dict],
    source_lang: str,
    batch_size: int = 10,
    progress_callback=None,
    group_by_article: bool = True,
    use_gemini: bool = True,
    use_claude: bool = True,
) -> list[dict]:
    """조문 리스트를 배치 단위로 이중 번역한다.

    Args:
        articles: [{'id': ..., 'text': ..., '조문번호': ...}, ...]
        source_lang: 'english' 또는 'chinese'
        batch_size: 배치 크기 (rate limit 방지)
        progress_callback: 진행률 콜백 함수 (current, total)
        group_by_article: True이면 조문 단위로 그룹화해서 번역 (빠름)
        use_gemini: Gemini 번역 사용 여부
        use_claude: Claude 번역 사용 여부

    Returns:
        [{'id', 'original', 'gemini', 'claude', 'diff_summary'}, ...]
    """
    if group_by_article and articles and '조문번호' in articles[0]:
        # 조문 단위로 그룹화해서 번역 (개별 API 호출)
        return _translate_by_article_group(articles, source_lang, progress_callback, use_gemini, use_claude)

    # 기존 방식: 항목별 개별 번역
    system_prompt = _get_system_prompt(source_lang)
    results = []
    total = len(articles)

    for i, article in enumerate(articles):
        text = article["text"]
        article_id = article["id"]

        # 전문(서문) 또는 삭제 조문은 번역 스킵
        if article_id == "전문":
            result = {
                "id": article_id,
                "original": text,
                "gemini": "(서문 — 번역 생략)",
                "claude": "(서문 — 번역 생략)",
                "diff_summary": "-",
            }
            # 구조 정보 보존
            for key in ["편", "장", "절", "조문번호", "조문제목", "항", "호"]:
                if key in article:
                    result[key] = article[key]
            results.append(result)
            if progress_callback:
                progress_callback(i + 1, total)
            continue

        if article_id.endswith("(삭제)") or text == "(삭제)":
            result = {
                "id": article_id,
                "original": "(삭제)",
                "gemini": "(삭제)",
                "claude": "(삭제)",
                "diff_summary": "-",
            }
            # 구조 정보 보존
            for key in ["편", "장", "절", "조문번호", "조문제목", "항", "호"]:
                if key in article:
                    result[key] = article[key]
            results.append(result)
            if progress_callback:
                progress_callback(i + 1, total)
            continue

        # Gemini 번역
        if use_gemini:
            gemini_text = translate_gemini(text, system_prompt)
            time.sleep(1)
        else:
            gemini_text = "(Gemini 미사용)"

        # Claude 번역
        if use_claude:
            claude_text = translate_claude(text, system_prompt)
            time.sleep(1)
        else:
            claude_text = "(Claude 미사용)"

        # 차이 요약
        if use_gemini and use_claude:
            diff = summarize_diff(gemini_text, claude_text)
        else:
            diff = "-"

        result = {
            "id": article_id,
            "original": text,
            "gemini": gemini_text,
            "claude": claude_text,
            "diff_summary": diff,
        }
        # 원본 article의 구조 정보 보존 (편/장/절/조문번호/조문제목/항/호)
        for key in ["편", "장", "절", "조문번호", "조문제목", "항", "호"]:
            if key in article:
                result[key] = article[key]
        results.append(result)

        # 배치 간 대기 (rate limit 방지)
        if (i + 1) % batch_size == 0:
            time.sleep(2)

        if progress_callback:
            progress_callback(i + 1, total)

    return results


def _translate_by_article_group(
    articles: list[dict],
    source_lang: str,
    progress_callback=None,
    use_gemini: bool = True,
    use_claude: bool = True,
) -> list[dict]:
    """조문 단위로 그룹화해서 동시 번역한다 (빠른 번역).

    조문 간 동시 처리(max_workers=5)로 번역 속도를 크게 개선한다.
    각 조문 내부에서는 Gemini+Claude 병렬 번역을 유지한다.

    Args:
        articles: [{'id': ..., 'text': ..., '조문번호': ...}, ...]
        source_lang: 'english' 또는 'chinese'
        progress_callback: 진행률 콜백
        use_gemini: Gemini 번역 사용 여부
        use_claude: Claude 번역 사용 여부

    Returns:
        [{'id', 'original', 'gemini', 'claude', 'diff_summary'}, ...]
    """
    import threading
    from collections import defaultdict
    from concurrent.futures import ThreadPoolExecutor, as_completed

    system_prompt = _get_system_prompt(source_lang)

    # 조문 번호별로 그룹화
    groups = defaultdict(list)
    for article in articles:
        article_num = article.get('조문번호', article['id'])
        groups[article_num].append(article)

    total_groups = len(groups)

    # 단일 조문 그룹 번역 내부 함수
    def _translate_one(article_num, group):
        """단일 조문 그룹을 번역하여 결과 리스트를 반환한다."""
        group_results = []

        # 전문이나 삭제 조문 처리
        if article_num == "전문":
            for article in group:
                result = {
                    "id": article["id"],
                    "original": article["text"],
                    "gemini": "(서문 — 번역 생략)",
                    "claude": "(서문 — 번역 생략)",
                    "diff_summary": "-",
                }
                for key in ["편", "장", "절", "조문번호", "조문제목", "항", "호"]:
                    if key in article:
                        result[key] = article[key]
                group_results.append(result)
            return group_results

        if article_num.endswith("(삭제)"):
            for article in group:
                result = {
                    "id": article["id"],
                    "original": "(삭제)",
                    "gemini": "(삭제)",
                    "claude": "(삭제)",
                    "diff_summary": "-",
                }
                for key in ["편", "장", "절", "조문번호", "조문제목", "항", "호"]:
                    if key in article:
                        result[key] = article[key]
                group_results.append(result)
            return group_results

        # 조문 전체 텍스트 합치기 (항/호/목 번호 포함)
        combined_parts = []
        for art in group:
            text = str(art.get("text", "")).strip()
            if not text:
                continue

            prefix = ""
            항 = art.get("항", "")
            호 = art.get("호", "")
            목 = art.get("목", "")

            if 항 and str(항).strip():
                try:
                    항_num = int(float(항))
                    prefix = f"({항_num}) "
                except:
                    prefix = f"({항}) "

            if 호 and str(호).strip():
                try:
                    호_num = int(float(호))
                    prefix += f"{호_num}. "
                except:
                    prefix += f"({호}) "

            if 목 and str(목).strip():
                prefix += f"({목}) "

            combined_parts.append(prefix + text)

        combined_text = "\n\n".join(combined_parts)

        # 병렬 번역 (Gemini와 Claude를 동시에 실행)
        gemini_text = "(Gemini 미사용)"
        claude_text = "(Claude 미사용)"

        futures = {}
        with ThreadPoolExecutor(max_workers=2) as executor:
            if use_gemini:
                futures['gemini'] = executor.submit(translate_gemini, combined_text, system_prompt)
            if use_claude:
                futures['claude'] = executor.submit(translate_claude, combined_text, system_prompt)

            for service, future in futures.items():
                try:
                    if service == 'gemini':
                        gemini_text = future.result(timeout=120)
                    elif service == 'claude':
                        claude_text = future.result(timeout=120)
                except Exception as e:
                    if service == 'gemini':
                        gemini_text = f"(번역 실패: {e})"
                    elif service == 'claude':
                        claude_text = f"(번역 실패: {e})"

        # 차이 요약
        if use_gemini and use_claude and "(번역 실패" not in gemini_text and "(번역 실패" not in claude_text:
            diff = summarize_diff(gemini_text, claude_text)
        else:
            diff = "-"

        # 조 단위로 각 항목에 전체 번역 결과 할당
        for i, article in enumerate(group):
            result = {
                "id": article["id"],
                "original": combined_text if i == 0 else article["text"],
                "gemini": gemini_text,
                "claude": claude_text,
                "diff_summary": diff if i == 0 else "-",
            }
            for key in ["편", "장", "절", "조문번호", "조문제목", "항", "호"]:
                if key in article:
                    result[key] = article[key]
            group_results.append(result)

        return group_results

    # 동시 실행 (max_workers=5: 동시 5개 조문 처리)
    lock = threading.Lock()
    current = [0]
    ordered_results = [None] * total_groups

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_idx = {}
        for idx, (article_num, group) in enumerate(groups.items()):
            f = executor.submit(_translate_one, article_num, group)
            future_to_idx[f] = idx

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                ordered_results[idx] = future.result()
            except Exception as e:
                # 예외 발생 시 해당 그룹의 모든 항목에 오류 결과 할당
                article_num, group = list(groups.items())[idx]
                error_results = []
                for article in group:
                    result = {
                        "id": article["id"],
                        "original": article.get("text", ""),
                        "gemini": f"(번역 오류: {e})",
                        "claude": f"(번역 오류: {e})",
                        "diff_summary": "-",
                    }
                    for key in ["편", "장", "절", "조문번호", "조문제목", "항", "호"]:
                        if key in article:
                            result[key] = article[key]
                    error_results.append(result)
                ordered_results[idx] = error_results

            with lock:
                current[0] += 1
                if progress_callback:
                    progress_callback(current[0], total_groups)

    # 순서대로 결과 조립
    results = []
    for group_results in ordered_results:
        if group_results:
            results.extend(group_results)

    return results


def _detect_number_pattern(original_texts: list[str]) -> str | None:
    """원문 텍스트에서 항/호 번호 패턴을 감지한다.

    Returns:
        감지된 패턴 문자열 또는 None
    """
    if not original_texts or len(original_texts) < 2:
        return None

    # 원문 각 항목의 시작 부분에서 번호 패턴 확인
    paren_count = 0  # (1), (2) 패턴
    alpha_paren_count = 0  # (a), (b) 패턴
    dot_count = 0  # 1., 2. 패턴
    circled_count = 0  # ①② 패턴

    for txt in original_texts:
        stripped = txt.strip()
        if re.match(r'^\(\d+\)', stripped):
            paren_count += 1
        elif re.match(r'^\([a-z]\)', stripped):
            alpha_paren_count += 1
        elif re.match(r'^\d+\.', stripped):
            dot_count += 1
        elif re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮]', stripped):
            circled_count += 1

    threshold = len(original_texts) * 0.5
    if paren_count >= threshold:
        return "paren_num"  # (1), (2)
    if alpha_paren_count >= threshold:
        return "paren_alpha"  # (a), (b)
    if dot_count >= threshold:
        return "dot_num"  # 1., 2.
    if circled_count >= threshold:
        return "circled"  # ①②
    return None


def _split_translation(
    text: str,
    expected_count: int,
    original_texts: list[str] | None = None,
) -> list[str]:
    """번역 결과를 항/호별로 분리한다.

    Args:
        text: 번역된 텍스트
        expected_count: 예상 항목 수
        original_texts: 원문 텍스트 리스트 (패턴 힌트용)

    Returns:
        분리된 텍스트 리스트
    """
    if expected_count <= 1:
        return [text]

    # 원문에서 번호 패턴 감지
    detected = _detect_number_pattern(original_texts) if original_texts else None

    # 패턴별 분리 시도 순서 결정
    # non-capturing group을 사용하여 split 시 캡처 그룹 문제 방지
    split_patterns = []
    if detected == "paren_num":
        split_patterns = [
            r'(?=\(\d+\)\s)',      # (1) 앞에서 분리 (lookahead)
            r'(?=\n\(\d+\))',      # 줄바꿈 + (1)
        ]
    elif detected == "paren_alpha":
        split_patterns = [
            r'(?=\([a-z]\)\s)',
            r'(?=\n\([a-z]\))',
        ]
    elif detected == "dot_num":
        split_patterns = [
            r'(?=(?:^|\n)\d+\.\s)',
        ]
    elif detected == "circled":
        split_patterns = [
            r'(?=[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮])',
        ]

    # 감지 패턴이 없으면 일반적인 패턴들 모두 시도
    if not split_patterns:
        split_patterns = [
            r'(?=\(\d+\)\s)',
            r'(?=\n\(\d+\))',
            r'(?=\([a-z]\)\s)',
            r'(?=(?:^|\n)\d+\.\s)',
            r'(?=[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮])',
        ]

    for pattern in split_patterns:
        parts = re.split(pattern, text, flags=re.MULTILINE)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) >= expected_count:
            return parts[:expected_count]

    # 단락(빈 줄) 기반 분리
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    if len(paragraphs) >= expected_count:
        return paragraphs[:expected_count]

    # 단일 줄바꿈 기반 분리
    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
    if len(lines) >= expected_count:
        # 줄 수가 expected_count보다 많으면 균등 분배
        if len(lines) == expected_count:
            return lines
        # 줄을 expected_count 그룹으로 균등 분할
        chunk_size = len(lines) / expected_count
        result = []
        for i in range(expected_count):
            start = int(i * chunk_size)
            end = int((i + 1) * chunk_size)
            result.append('\n'.join(lines[start:end]))
        return result

    # 최후의 수단: 전체 텍스트를 모든 항목에 동일하게 반환
    return [text] * expected_count


def translate_batch_smart(
    articles: list[dict],
    source_lang: str,
    progress_callback=None,
    use_gemini: bool = True,
    use_claude: bool = True,
    batch_size: int = 15,
) -> list[dict]:
    """스마트 배치 번역: 조문들을 적절한 크기로 묶어서 일괄 번역한다.

    Args:
        articles: [{'id': ..., 'text': ..., '조문번호': ...}, ...]
        source_lang: 'english', 'chinese', 'german' 등
        progress_callback: 진행률 콜백
        use_gemini: Gemini 번역 사용 여부
        use_claude: Claude 번역 사용 여부
        batch_size: 한 번에 번역할 조문 수 (기본 15개)

    Returns:
        [{'id', 'original', 'gemini', 'claude', 'diff_summary'}, ...]
    """
    import json

    system_prompt = _get_system_prompt(source_lang)

    # 조문 번호별로 그룹화
    from collections import defaultdict
    groups = defaultdict(list)
    for article in articles:
        article_num = article.get('조문번호', article['id'])
        groups[article_num].append(article)

    # 전문/삭제 조문 분리
    valid_groups = {}
    skip_groups = {}

    for article_num, group in groups.items():
        if article_num == "전문" or article_num.endswith("(삭제)"):
            skip_groups[article_num] = group
        else:
            valid_groups[article_num] = group

    if not valid_groups:
        return _translate_by_article_group(articles, source_lang, progress_callback, use_gemini, use_claude)

    # 조문을 배치로 나누기
    article_nums = list(valid_groups.keys())
    batches = [article_nums[i:i + batch_size] for i in range(0, len(article_nums), batch_size)]

    results = []
    total_batches = len(batches)

    for batch_idx, batch_article_nums in enumerate(batches):
        # 배치 내 조문 텍스트 구성
        batch_texts = {}
        for article_num in batch_article_nums:
            group = valid_groups[article_num]
            combined_parts = []

            for art in group:
                text = str(art.get("text", "")).strip()
                if not text:
                    continue

                # 항/호/목 번호 추가
                prefix = ""
                항 = art.get("항", "")
                호 = art.get("호", "")
                목 = art.get("목", "")

                if 항 and str(항).strip():
                    try:
                        항_num = int(float(항))
                        prefix = f"({항_num}) "
                    except:
                        prefix = f"({항}) "

                if 호 and str(호).strip():
                    try:
                        호_num = int(float(호))
                        prefix += f"{호_num}. "
                    except:
                        prefix += f"({호}) "

                if 목 and str(목).strip():
                    prefix += f"({목}) "

                combined_parts.append(prefix + text)

            batch_texts[article_num] = "\n\n".join(combined_parts)

        # 배치 프롬프트 구성
        texts_json = json.dumps(batch_texts, ensure_ascii=False, indent=2)
        batch_content = f"""다음은 여러 조문의 텍스트입니다. 각 조문을 개별적으로 번역하여 JSON 형식으로 응답해주세요.

**입력:**
{texts_json}

**응답 형식 (JSON만):**
```json
{{
  "조문ID1": "번역문1",
  "조문ID2": "번역문2"
}}
```"""

        # Gemini 배치 번역
        gemini_translations = {}
        if use_gemini:
            try:
                gemini_response = translate_gemini(batch_content, system_prompt)
                if "```json" in gemini_response:
                    json_start = gemini_response.find("```json") + 7
                    json_end = gemini_response.find("```", json_start)
                    json_text = gemini_response[json_start:json_end].strip()
                else:
                    json_text = gemini_response
                gemini_translations = json.loads(json_text)
            except Exception as e:
                print(f"⚠️ Gemini 배치 {batch_idx+1} 번역 실패: {e}")
                # 실패 시 이 배치는 개별 번역으로 폴백
                for article_num in batch_article_nums:
                    text = batch_texts[article_num]
                    gemini_translations[article_num] = translate_gemini(text, system_prompt)
                    time.sleep(0.5)

        # Claude 배치 번역
        claude_translations = {}
        if use_claude:
            try:
                claude_response = translate_claude(batch_content, system_prompt)
                if "```json" in claude_response:
                    json_start = claude_response.find("```json") + 7
                    json_end = claude_response.find("```", json_start)
                    json_text = claude_response[json_start:json_end].strip()
                else:
                    json_text = claude_response
                claude_translations = json.loads(json_text)
            except Exception as e:
                print(f"⚠️ Claude 배치 {batch_idx+1} 번역 실패: {e}")
                # 실패 시 이 배치는 개별 번역으로 폴백
                for article_num in batch_article_nums:
                    text = batch_texts[article_num]
                    claude_translations[article_num] = translate_claude(text, system_prompt)
                    time.sleep(0.5)

        # 배치 결과 구성
        for article_num in batch_article_nums:
            group = valid_groups[article_num]
            combined_text = batch_texts[article_num]

            gemini_text = gemini_translations.get(str(article_num), "(Gemini 미사용)")
            claude_text = claude_translations.get(str(article_num), "(Claude 미사용)")

            # 차이 요약
            if use_gemini and use_claude and gemini_text != "(Gemini 미사용)" and claude_text != "(Claude 미사용)":
                diff = summarize_diff(gemini_text, claude_text)
            else:
                diff = "-"

            # 각 항목에 결과 할당
            for i, article in enumerate(group):
                result = {
                    "id": article["id"],
                    "original": combined_text if i == 0 else article["text"],
                    "gemini": gemini_text,
                    "claude": claude_text,
                    "diff_summary": diff if i == 0 else "-",
                }
                for key in ["편", "장", "절", "조문번호", "조문제목", "항", "호"]:
                    if key in article:
                        result[key] = article[key]
                results.append(result)

        # 진행률 업데이트
        if progress_callback:
            progress_callback(batch_idx + 1, total_batches)

    # 스킵된 조문 처리
    for article_num, group in skip_groups.items():
        for article in group:
            if article_num == "전문":
                result = {
                    "id": article["id"],
                    "original": article["text"],
                    "gemini": "(서문 — 번역 생략)",
                    "claude": "(서문 — 번역 생략)",
                    "diff_summary": "-",
                }
            else:
                result = {
                    "id": article["id"],
                    "original": "(삭제)",
                    "gemini": "(삭제)",
                    "claude": "(삭제)",
                    "diff_summary": "-",
                }
            for key in ["편", "장", "절", "조문번호", "조문제목", "항", "호"]:
                if key in article:
                    result[key] = article[key]
            results.append(result)

    return results
