import hashlib
import json
import os
import pickle
import re
import time

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# 모듈 레벨 캐시: 모델을 한 번만 로드
_model = None

# 임베딩 캐시 저장 폴더
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".embedding_cache")


def _get_model() -> SentenceTransformer:
    """다국어 임베딩 모델을 로드한다 (싱글턴)."""
    global _model
    if _model is None:
        # 타임아웃 설정 (모델 다운로드용 - 최초 1회만)
        import os
        os.environ['HF_HUB_TIMEOUT'] = '300'  # 5분
        _model = SentenceTransformer("intfloat/multilingual-e5-large")
    return _model


def _prepare_text(text: str, is_query: bool = False) -> str:
    """E5 모델 입력 형식에 맞게 접두사를 추가한다."""
    prefix = "query: " if is_query else "passage: "
    return prefix + text.strip()


def _make_cache_key(korea_articles: list[dict]) -> str:
    """한국법 조문 목록으로부터 캐시 키(해시)를 생성한다."""
    content = json.dumps(
        [{"id": a["id"], "text": a["text"], "source": a.get("source", "")}
         for a in korea_articles],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _load_cache(cache_key: str) -> dict | None:
    """캐시 파일이 존재하면 로드한다."""
    cache_path = os.path.join(_CACHE_DIR, f"{cache_key}.pkl")
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return pickle.load(f)
    return None


def _save_cache(cache_key: str, index: dict) -> None:
    """임베딩 인덱스를 캐시 파일로 저장한다."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(_CACHE_DIR, f"{cache_key}.pkl")
    with open(cache_path, "wb") as f:
        pickle.dump(index, f)


def build_korea_index(korea_articles: list[dict], use_cache: bool = True) -> dict:
    """한국법 조문 임베딩 인덱스를 구축한다.

    Args:
        korea_articles: 한국법 조문 리스트
        use_cache: 캐시 사용 여부 (구조화 엑셀은 계속 수정되므로 False 권장)

    같은 한국법 조합이면 캐시에서 불러오고,
    처음이면 임베딩 후 캐시에 저장한다.
    """
    cache_key = _make_cache_key(korea_articles)

    if use_cache:
        cached = _load_cache(cache_key)
        if cached is not None:
            return cached

    model = _get_model()
    texts = [_prepare_text(a["text"]) for a in korea_articles]
    embeddings = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)
    index = {
        "articles": korea_articles,
        "embeddings": np.array(embeddings),
    }

    if use_cache:
        _save_cache(cache_key, index)
    return index


def find_similar_korean(
    foreign_article: dict,
    korea_index: dict,
    top_k: int = 1,
) -> list[dict]:
    """임베딩 기반 유사 조문 검색 (폴백용)."""
    if not korea_index["articles"]:
        return []

    model = _get_model()
    query_text = _prepare_text(foreign_article["text"], is_query=True)
    query_embedding = model.encode([query_text], normalize_embeddings=True)

    scores = cosine_similarity(query_embedding, korea_index["embeddings"])[0]
    top_indices = np.argsort(scores)[::-1][:top_k]

    results = []
    for idx in top_indices:
        article = korea_index["articles"][idx]
        results.append({
            "korean_id": article["id"],
            "korean_text": article["text"],
            "score": float(scores[idx]),
            "source": article.get("source", ""),
        })
    return results


# ── AI 기반 매칭 ─────────────────────────────────────────────

def _call_gemini(prompt: str, system: str, max_retries: int = 3) -> str:
    """Gemini API를 재시도 포함하여 호출한다."""
    import streamlit as st
    import google.generativeai as genai

    api_key = st.secrets.get("GEMINI_API_KEY", "")
    if not api_key or api_key == "your-key-here":
        return ""

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=system)

    for attempt in range(max_retries):
        try:
            response = model.generate_content(
                prompt,
                request_options={"timeout": 120},
            )
            time.sleep(1)
            return response.text.strip()
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(3 * (attempt + 1))
            else:
                return ""


def _call_claude(prompt: str, system: str, max_retries: int = 3) -> str:
    """Claude API를 재시도 포함하여 호출한다."""
    import streamlit as st
    import anthropic

    api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    if not api_key or api_key == "your-key-here":
        return ""

    for attempt in range(max_retries):
        try:
            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            time.sleep(1)
            return message.content[0].text.strip()
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(3 * (attempt + 1))
            else:
                return ""


def select_relevant_korean_laws(
    foreign_law_name: str,
    foreign_sample_text: str,
    korea_law_names: list[str],
) -> list[str]:
    """[1단계] AI가 해외 법령의 주제를 보고 관련 한국법을 선택한다.

    Args:
        foreign_law_name: 해외 법령 파일명
        foreign_sample_text: 해외 법령 앞부분 샘플 (번역문)
        korea_law_names: 한국법 파일명 리스트

    Returns:
        관련 한국법 파일명 리스트 (1~2개)
    """
    law_list = "\n".join(f"{i+1}. {name}" for i, name in enumerate(korea_law_names))

    prompt = (
        f"해외 법령: {foreign_law_name}\n\n"
        f"해외 법령 내용 샘플 (번역문):\n{foreign_sample_text[:1000]}\n\n"
        f"아래 한국 법령 목록 중에서 위 해외 법령과 규율 분야가 가장 관련 있는 "
        f"한국 법령을 1~2개 선택하십시오.\n\n"
        f"{law_list}\n\n"
        f"반드시 다음 형식으로만 답하십시오 (번호만):\n"
        f"선택: 1, 3"
    )

    answer = _call_gemini(
        prompt,
        "당신은 한국 지식재산권법 전문가입니다. 해외 법령의 규율 분야를 파악하고 "
        "가장 관련 있는 한국 법령을 정확히 선택합니다."
    )

    if not answer:
        return korea_law_names  # 실패 시 전체 반환

    # 번호 파싱
    selected = []
    for line in answer.split("\n"):
        if "선택" in line or any(c.isdigit() for c in line):
            nums = re.findall(r"\d+", line)
            for n in nums:
                idx = int(n) - 1
                if 0 <= idx < len(korea_law_names):
                    selected.append(korea_law_names[idx])

    return selected if selected else korea_law_names


def match_article_with_korean_law(
    translated_text: str,
    foreign_article_id: str,
    korean_articles: list[dict],
    korean_law_name: str,
    foreign_article_title: str = "",
) -> dict | None:
    """[2단계] AI가 해외법 번역문을 읽고 한국법 조문 목록에서 매칭한다.

    Args:
        translated_text: 해외법 번역문 (한국어)
        foreign_article_id: 해외법 조문 번호
        korean_articles: 해당 한국법의 조문 리스트 [{'id':..., 'text':...}, ...]
        korean_law_name: 한국법 파일명
        foreign_article_title: 해외법 조문 제목 (있는 경우)

    Returns:
        {'korean_id', 'korean_text', 'score', 'source', 'ai_reason'} or None
    """
    if not korean_articles:
        return None

    # 응답 파싱 헬퍼 함수
    def parse_ai_response(answer):
        """AI 응답에서 선택과 이유 추출"""
        if not answer or "없음" in answer:
            return None, ""
        chosen_id = None
        ai_reason = ""
        for line in answer.split("\n"):
            line = line.strip()
            if line.startswith("선택:"):
                text = line.replace("선택:", "").strip().strip("[]").strip()
                if text and text != "없음":
                    chosen_id = text
            elif line.startswith("이유:"):
                ai_reason = line.replace("이유:", "").strip()
        return chosen_id, ai_reason

    # 조문 찾기 헬퍼 함수
    def find_korean_article(chosen_id, korean_articles):
        """선택된 조문 ID로 한국법 조문 찾기"""
        if not chosen_id:
            return None
        # 정확히 일치
        for a in korean_articles:
            if a["id"] == chosen_id:
                return a
        # 부분 매칭
        for a in korean_articles:
            if chosen_id in a["id"] or a["id"] in chosen_id:
                return a
        # 숫자만 추출해서 비교
        chosen_nums = re.findall(r"\d+", chosen_id)
        for a in korean_articles:
            article_nums = re.findall(r"\d+", a["id"])
            if chosen_nums and article_nums and chosen_nums[0] == article_nums[0]:
                return a
        return None

    # 1단계: 조문 제목 기반 AI 매칭 (Gemini + Claude)
    if foreign_article_title and foreign_article_title.strip():
        # 한국법 조문 제목 목록 구성
        title_list = ""
        for a in korean_articles:
            if a["id"] == "전문":
                continue
            korean_title = a.get("title", "").strip()
            if korean_title:
                title_list += f"- {a['id']}: {korean_title}\n"

        # 제목이 있는 한국법 조문이 있으면 AI로 제목 매칭
        if title_list:
            title_prompt = (
                f"외국법 조문 제목: '{foreign_article_title}'\n\n"
                f"아래 한국 법령({korean_law_name})의 조문 제목 목록에서 "
                f"위 외국법 조문 제목과 의미적으로 동일하거나 매우 유사한 조문을 1개만 선택하십시오.\n"
                f"의미가 명확히 다르거나 유사한 조문이 없으면 반드시 '없음'이라고 답하십시오.\n\n"
                f"{title_list}\n"
                f"반드시 다음 형식으로만 답하십시오:\n"
                f"선택: [조문번호] (또는 '없음')\n"
                f"이유: [1문장 이유]"
            )

            title_system = (
                "당신은 법률 전문가입니다. 조문 제목의 의미를 정확히 비교하여 "
                "동일하거나 매우 유사한 경우만 매칭하십시오. "
                "불확실하거나 의미가 다르면 반드시 '없음'으로 답하십시오."
            )

            # Gemini와 Claude 동시 호출
            gemini_answer = _call_gemini(title_prompt, title_system)
            claude_answer = _call_claude(title_prompt, title_system)

            gemini_id, gemini_reason = parse_ai_response(gemini_answer)
            claude_id, claude_reason = parse_ai_response(claude_answer)

            # 두 AI가 같은 조문을 선택한 경우만 매칭
            if gemini_id and claude_id and gemini_id == claude_id:
                article = find_korean_article(gemini_id, korean_articles)
                if article:
                    return {
                        "korean_id": article["id"],
                        "korean_text": article["text"],
                        "score": 1.0,
                        "source": article.get("source", korean_law_name),
                        "ai_reason": f"[제목 매칭 - 양쪽 AI 일치] {gemini_reason or claude_reason}",
                    }

    # 2단계: 조문 내용 기반 AI 매칭 (Gemini + Claude)
    # 한국법 조문 목록 구성 (조문번호 + 앞 150자)
    article_list = ""
    for a in korean_articles:
        if a["id"] == "전문":
            continue
        summary = a["text"][:150].replace("\n", " ")
        article_list += f"- {a['id']}: {summary}\n"

    content_prompt = (
        f"해외 법령 조문 ({foreign_article_id}) 번역문:\n"
        f"{translated_text[:500]}\n\n"  # 너무 길면 잘라서 전달
        f"아래 한국 법령({korean_law_name})의 조문 목록에서 "
        f"위 해외법 조문과 규율 내용이 가장 유사한 조문을 1개 선택하십시오.\n"
        f"유사한 조문이 전혀 없으면 '없음'이라고 답하십시오.\n\n"
        f"{article_list}\n"
        f"반드시 다음 형식으로만 답하십시오:\n"
        f"선택: [조문번호] (또는 '없음')\n"
        f"이유: [1문장 이유]"
    )

    content_system = (
        "당신은 한국 법률 전문가입니다. 해외 법령 조문의 규율 내용을 정확히 파악하고, "
        "한국 법령에서 동일하거나 가장 유사한 내용을 규율하는 조문을 찾습니다. "
        "조문 번호가 같다고 내용이 같은 것이 아닙니다. 반드시 내용을 기준으로 판단하십시오. "
        "불확실하거나 유사한 조문이 없으면 '없음'으로 답하십시오."
    )

    # Gemini와 Claude 동시 호출
    gemini_answer = _call_gemini(content_prompt, content_system)
    claude_answer = _call_claude(content_prompt, content_system)

    gemini_id, gemini_reason = parse_ai_response(gemini_answer)
    claude_id, claude_reason = parse_ai_response(claude_answer)

    # 두 AI가 같은 조문을 선택한 경우만 매칭
    if gemini_id and claude_id and gemini_id == claude_id:
        article = find_korean_article(gemini_id, korean_articles)
        if article:
            return {
                "korean_id": article["id"],
                "korean_text": article["text"],
                "score": 1.0,
                "source": article.get("source", korean_law_name),
                "ai_reason": f"[내용 매칭 - 양쪽 AI 일치] {gemini_reason or claude_reason}",
            }

    # 두 AI가 다른 결과를 낸 경우 → 매칭 실패
    return None


def find_similar_korean_ai(
    foreign_article: dict,
    translated_text: str,
    korea_index: dict,
    relevant_law_sources: list[str] | None = None,
    foreign_article_title: str = "",
) -> list[dict]:
    """AI 기반 한국법 매칭 (2단계).

    Args:
        foreign_article: {'id': '조문번호', 'text': '원문', '조문제목': '제목'(선택)}
        translated_text: 해외법 번역문 (한국어)
        korea_index: build_korea_index()의 반환값
        relevant_law_sources: 1단계에서 선택된 관련 한국법 파일명 리스트
        foreign_article_title: 해외법 조문 제목 (있는 경우)

    Returns:
        [{'korean_id', 'korean_text', 'score', 'source', 'ai_reason'}]
    """
    if not korea_index["articles"]:
        return []

    # 관련 한국법별로 조문 그룹핑
    articles_by_law: dict[str, list[dict]] = {}
    for a in korea_index["articles"]:
        src = a.get("source", "")
        if relevant_law_sources and src not in relevant_law_sources:
            continue
        articles_by_law.setdefault(src, []).append(a)

    if not articles_by_law:
        # 관련법이 없으면 전체에서 시도
        for a in korea_index["articles"]:
            src = a.get("source", "")
            articles_by_law.setdefault(src, []).append(a)

    # 각 관련 한국법에서 매칭 시도
    best_match = None
    # 조문 제목 추출 (제공되지 않은 경우 foreign_article에서 가져오기)
    if not foreign_article_title and "조문제목" in foreign_article:
        foreign_article_title = str(foreign_article.get("조문제목", ""))

    for law_source, articles in articles_by_law.items():
        result = match_article_with_korean_law(
            translated_text,
            foreign_article["id"],
            articles,
            law_source,
            foreign_article_title,
        )
        if result:
            best_match = result
            break  # 첫 번째 매칭에서 성공하면 종료

    if best_match:
        return [best_match]

    # AI 매칭 실패 시 매칭 없음 반환 (무조건 매칭할 필요 없음)
    return []


def _parse_batch_matches(response_text: str, korea_articles: list[dict]) -> dict[str, list[dict]]:
    """AI 응답 텍스트를 파싱하여 매칭 결과 딕셔너리를 반환한다."""
    # JSON 파싱
    if "```json" in response_text:
        json_start = response_text.find("```json") + 7
        json_end = response_text.find("```", json_start)
        json_text = response_text[json_start:json_end].strip()
    else:
        json_text = response_text

    result = json.loads(json_text)
    matches = result.get('matches', [])

    result_dict = {}
    for match in matches:
        foreign_id = str(match.get('foreign_id', ''))
        korean_id = match.get('korean_id')

        if korean_id and korean_id != "null":
            korean_text = ""
            korean_source = ""
            for k_art in korea_articles:
                if str(k_art['id']) == str(korean_id):
                    korean_text = k_art.get('text', '')
                    korean_source = k_art.get('source', '')
                    break

            result_dict[foreign_id] = [{
                'korean_id': str(korean_id),
                'korean_title': match.get('korean_title', ''),
                'korean_text': korean_text,
                'score': float(match.get('score', 0.9)),
                'ai_reason': match.get('reason', ''),
                'source': korean_source
            }]
        else:
            result_dict[foreign_id] = []

    return result_dict


def find_similar_korean_batch(
    foreign_articles: list[dict],
    korea_index: dict,
    relevant_law_sources: list[str] | None = None,
    batch_size: int = 30,
) -> dict[str, list[dict]]:
    """외국법 조문들을 한국법과 일괄 매칭한다.

    조문 수가 많으면 배치로 나누어 처리한다.

    Args:
        foreign_articles: 외국법 조문 리스트
            각 조문은 {'id': 조문번호, 'text': 원문, '조문제목': 제목, 'translated': 번역문} 포함
        korea_index: 한국법 인덱스 {'articles': [...]}
        relevant_law_sources: 매칭 대상 한국법 필터 (예: ["특허법", "실용신안법"])
        batch_size: 한 번에 매칭할 외국법 조문 수 (기본 30개)

    Returns:
        조문 ID를 키로, 매칭 결과 리스트를 값으로 하는 딕셔너리
        예: {'1': [{'korean_id': '2', 'score': 0.95, ...}], '2': [...], ...}
    """
    import anthropic
    import streamlit as st

    # API 키 확인
    api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("❌ ANTHROPIC_API_KEY가 설정되지 않았습니다.")
        return {}

    # 한국법 조문 필터링
    korea_articles = korea_index.get("articles", [])
    if relevant_law_sources:
        korea_articles = [
            art for art in korea_articles
            if art.get("source", "") in relevant_law_sources
        ]

    # 한국법 조문 리스트 (공통)
    korea_list_str = "\n".join([
        f"제{art['id']}조: {art.get('title', '')}"
        for art in korea_articles[:100]
    ])

    client = anthropic.Anthropic(api_key=api_key)

    # 배치 분할
    batches = [
        foreign_articles[i:i + batch_size]
        for i in range(0, len(foreign_articles), batch_size)
    ]

    all_results = {}
    total_batches = len(batches)

    for batch_idx, batch in enumerate(batches):
        if total_batches > 1:
            st.write(f"📦 배치 {batch_idx + 1}/{total_batches} 처리 중... ({len(batch)}개 조문)")

        foreign_list_str = "\n".join([
            f"{art['id']}: {art.get('조문제목', '')}"
            for art in batch
        ])

        prompt = f"""당신은 특허법 전문가입니다. 외국 특허법 조문들과 한국 특허법 조문들이 주어졌습니다.

**외국법 조문 제목:**
{foreign_list_str}

**한국 특허법 조문 제목:**
{korea_list_str}

각 외국법 조문에 대해 가장 유사한 한국 특허법 조문을 찾아주세요.

**응답 형식 (JSON):**
```json
{{
  "matches": [
    {{
      "foreign_id": "1",
      "korean_id": "2",
      "korean_title": "...",
      "score": 0.95,
      "reason": "매칭 이유"
    }},
    ...
  ]
}}
```

매칭이 없으면 korean_id를 null로 설정하세요. JSON 형식으로만 응답해주세요."""

        try:
            response_text = ""
            with client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=16000,
                messages=[{"role": "user", "content": prompt}]
            ) as stream:
                for text in stream.text_stream:
                    response_text += text

            batch_results = _parse_batch_matches(response_text, korea_articles)
            all_results.update(batch_results)

            if total_batches > 1:
                st.write(f"  ✅ 배치 {batch_idx + 1} 완료: {len(batch_results)}개 매칭")

        except Exception as e:
            st.error(f"❌ 배치 {batch_idx + 1} 매칭 오류: {e}")
            st.write("응답 내용:", response_text[:500] if 'response_text' in locals() else "응답 없음")

        # 배치 간 대기 (rate limit 방지)
        if batch_idx < total_batches - 1:
            time.sleep(2)

    st.write(f"📊 최종 매칭: {len(all_results)}개 조문")
    return all_results
