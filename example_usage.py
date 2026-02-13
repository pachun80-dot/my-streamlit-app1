"""법령 구조화 및 번역 - Python 직접 사용 예시

이 스크립트는 웹 UI 없이 Python 코드에서 직접
법령 구조화와 번역을 실행하는 방법을 보여줍니다.
"""

import os
import pandas as pd
from pathlib import Path

# 1. 구조화 작업에 필요한 함수들
from pdf_parser import (
    parse_pdf,                           # PDF 텍스트 추출
    parse_rtf,                           # RTF 텍스트 추출
    parse_german_xml,                    # 독일 XML 파싱
    extract_structured_articles,         # 텍스트 → DataFrame 구조화
    save_structured_to_excel,            # DataFrame → Excel 저장
    _detect_lang,                        # 언어 자동 감지
    _detect_format,                      # 포맷 자동 감지
)

# 2. 번역 작업에 필요한 함수들
from translator import translate_batch_smart

# HTML 파싱 (유럽 법령 등)
from html_parser import parse_eu_html_to_dataframe


# ================================================================
# 예시 1: PDF 법령 구조화
# ================================================================

def structurize_pdf(pdf_path: str, output_excel_path: str):
    """PDF 법령을 구조화하여 Excel로 저장

    Args:
        pdf_path: 입력 PDF 파일 경로
        output_excel_path: 출력 Excel 파일 경로
    """
    print(f"📄 PDF 파싱 시작: {pdf_path}")

    # 1단계: PDF에서 텍스트 추출
    text = parse_pdf(pdf_path)

    # 2단계: 언어 및 포맷 자동 감지
    lang = _detect_lang(text, pdf_path)
    format_type = _detect_format(pdf_path)

    print(f"  - 감지된 언어: {lang}")
    print(f"  - 감지된 포맷: {format_type}")

    # 3단계: 구조화 (텍스트 → DataFrame)
    df = extract_structured_articles(text, lang, format_type)

    print(f"  - 추출된 조문 수: {len(df)}")

    # 4단계: Excel 저장
    save_structured_to_excel(df, output_excel_path)

    print(f"✅ 구조화 완료: {output_excel_path}")

    return df


# ================================================================
# 예시 2: RTF 법령 구조화 (미국법)
# ================================================================

def structurize_rtf(rtf_path: str, output_excel_path: str):
    """RTF 법령을 구조화하여 Excel로 저장

    Args:
        rtf_path: 입력 RTF 파일 경로
        output_excel_path: 출력 Excel 파일 경로
    """
    print(f"📄 RTF 파싱 시작: {rtf_path}")

    # 1단계: RTF에서 텍스트 추출
    text = parse_rtf(rtf_path)

    # 2단계: 구조화 (미국법은 항상 english/usa)
    df = extract_structured_articles(text, "english", "usa")

    print(f"  - 추출된 조문 수: {len(df)}")

    # 3단계: Excel 저장
    save_structured_to_excel(df, output_excel_path)

    print(f"✅ 구조화 완료: {output_excel_path}")

    return df


# ================================================================
# 예시 3: 독일 XML 법령 구조화
# ================================================================

def structurize_german_xml(xml_path: str, output_excel_path: str):
    """독일 XML 법령을 구조화하여 Excel로 저장

    Args:
        xml_path: 입력 XML 파일 경로
        output_excel_path: 출력 Excel 파일 경로
    """
    print(f"📄 독일 XML 파싱 시작: {xml_path}")

    # 독일 XML은 별도 함수로 직접 DataFrame 반환
    df = parse_german_xml(xml_path)

    print(f"  - 추출된 조문 수: {len(df)}")

    # Excel 저장
    save_structured_to_excel(df, output_excel_path)

    print(f"✅ 구조화 완료: {output_excel_path}")

    return df


# ================================================================
# 예시 4: HTML 법령 구조화 (유럽 EPC)
# ================================================================

def structurize_eu_html(url: str, output_excel_path: str):
    """유럽 HTML 법령을 구조화하여 Excel로 저장

    Args:
        url: HTML 법령 URL
        output_excel_path: 출력 Excel 파일 경로
    """
    print(f"🌐 HTML 파싱 시작: {url}")

    # HTML 파싱 (내부에서 DataFrame 반환)
    df = parse_eu_html_to_dataframe(url)

    print(f"  - 추출된 조문 수: {len(df)}")

    # Excel 저장
    save_structured_to_excel(df, output_excel_path)

    print(f"✅ 구조화 완료: {output_excel_path}")

    return df


# ================================================================
# 예시 5: 구조화된 Excel을 번역
# ================================================================

def translate_structured_excel(
    input_excel_path: str,
    output_excel_path: str,
    source_lang: str = "english",
    use_gemini: bool = True,
    use_claude: bool = True,
):
    """구조화된 Excel 파일을 읽어서 번역하고 결과를 저장

    Args:
        input_excel_path: 구조화된 Excel 파일 경로
        output_excel_path: 번역 결과 Excel 파일 경로
        source_lang: 'english' 또는 'chinese'
        use_gemini: Gemini 번역 사용 여부
        use_claude: Claude 번역 사용 여부

    주의:
        - API 키가 설정되어 있어야 합니다 (.streamlit/secrets.toml)
        - GEMINI_API_KEY와 ANTHROPIC_API_KEY 필요
    """
    print(f"🌍 번역 시작: {input_excel_path}")

    # 1단계: Excel 읽기
    df = pd.read_excel(input_excel_path, sheet_name="법조문")

    print(f"  - 읽은 조문 수: {len(df)}")

    # 2단계: 번역용 데이터 준비
    # translate_batch_smart는 다음 형식을 기대합니다:
    # [{'id': ..., 'text': ..., '조문번호': ...}, ...]

    articles = []
    for idx, row in df.iterrows():
        article = {
            'id': f"{row.get('조문번호', '')}",
            'text': row.get('원문', ''),
            '조문번호': row.get('조문번호', ''),
            '항': row.get('항', ''),
            '호': row.get('호', ''),
        }
        articles.append(article)

    # 3단계: 번역 실행
    print(f"  - 번역 엔진: Gemini={use_gemini}, Claude={use_claude}")

    # 진행률 콜백 함수
    def progress_callback(current, total):
        percent = (current / total) * 100
        print(f"  - 진행률: {current}/{total} ({percent:.1f}%)")

    translated = translate_batch_smart(
        articles=articles,
        source_lang=source_lang,
        progress_callback=progress_callback,
        use_gemini=use_gemini,
        use_claude=use_claude,
    )

    # 4단계: 결과를 DataFrame으로 변환
    result_rows = []
    for item in translated:
        result_rows.append({
            '조문번호': item.get('id', ''),
            '원문': item.get('original', ''),
            'Gemini 번역': item.get('gemini', ''),
            'Claude 번역': item.get('claude', ''),
            '차이점 요약': item.get('diff_summary', ''),
        })

    result_df = pd.DataFrame(result_rows)

    # 5단계: Excel 저장
    with pd.ExcelWriter(output_excel_path, engine="openpyxl") as writer:
        result_df.to_excel(writer, index=False, sheet_name="번역비교")

        # 컬럼 너비 자동 조정
        worksheet = writer.sheets["번역비교"]
        for idx, col in enumerate(result_df.columns):
            worksheet.column_dimensions[chr(65 + idx)].width = 50

    print(f"✅ 번역 완료: {output_excel_path}")

    return result_df


# ================================================================
# 예시 6: 한 번에 구조화 + 번역
# ================================================================

def full_process(
    input_file: str,
    output_dir: str = "DATA/output",
    source_lang: str = "english",
):
    """법령 파일을 구조화하고 번역까지 한 번에 처리

    Args:
        input_file: 입력 파일 경로 (PDF/RTF/XML)
        output_dir: 출력 디렉토리
        source_lang: 'english' 또는 'chinese'
    """
    # 출력 디렉토리 생성
    os.makedirs(f"{output_dir}/구조화법률", exist_ok=True)
    os.makedirs(f"{output_dir}/번역비교결과", exist_ok=True)

    # 파일명 추출
    file_name = Path(input_file).stem
    ext = Path(input_file).suffix.lower()

    # 1단계: 구조화
    structured_path = f"{output_dir}/구조화법률/{file_name}_구조화.xlsx"

    if ext == ".pdf":
        df = structurize_pdf(input_file, structured_path)
    elif ext == ".rtf":
        df = structurize_rtf(input_file, structured_path)
    elif ext == ".xml":
        df = structurize_german_xml(input_file, structured_path)
    else:
        raise ValueError(f"지원하지 않는 파일 형식: {ext}")

    # 2단계: 번역
    translated_path = f"{output_dir}/번역비교결과/{file_name}_번역비교.xlsx"

    result_df = translate_structured_excel(
        input_excel_path=structured_path,
        output_excel_path=translated_path,
        source_lang=source_lang,
    )

    print("\n" + "="*60)
    print("🎉 전체 처리 완료!")
    print(f"  - 구조화 파일: {structured_path}")
    print(f"  - 번역 파일: {translated_path}")
    print("="*60)

    return df, result_df


# ================================================================
# 메인 실행 예시
# ================================================================

if __name__ == "__main__":
    # 예시 1: PDF 구조화만
    # structurize_pdf(
    #     pdf_path="DATA/EPC/european_patent_convention.pdf",
    #     output_excel_path="DATA/output/구조화법률/EPC_구조화.xlsx"
    # )

    # 예시 2: 구조화 + 번역 한 번에
    # full_process(
    #     input_file="DATA/EPC/european_patent_convention.pdf",
    #     output_dir="DATA/output",
    #     source_lang="english"
    # )

    # 예시 3: 이미 구조화된 파일만 번역
    # translate_structured_excel(
    #     input_excel_path="DATA/output/구조화법률/EPC_구조화.xlsx",
    #     output_excel_path="DATA/output/번역비교결과/EPC_번역비교.xlsx",
    #     source_lang="english"
    # )

    print("ℹ️  사용 방법:")
    print("   1. 위의 예시 코드에서 주석을 해제하고 파일 경로를 수정하세요")
    print("   2. API 키가 .streamlit/secrets.toml에 설정되어 있는지 확인하세요")
    print("   3. python example_usage.py 로 실행하세요")
