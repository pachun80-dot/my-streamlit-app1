"""중국 특허법 HTML 파서 테스트"""

from html_parser import parse_china_html_to_dataframe

# 중국 특허법 URL
china_patent_law_url = "https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html"

print("=" * 60)
print("중국 특허법 HTML 파싱 테스트")
print("=" * 60)
print(f"\nURL: {china_patent_law_url}")
print("\n파싱 시작...")

try:
    # HTML 파싱
    df = parse_china_html_to_dataframe(china_patent_law_url)

    print(f"\n✅ 파싱 성공!")
    print(f"총 항목 수: {len(df)}")
    print(f"\n컬럼: {list(df.columns)}")

    # 처음 5개 항목 미리보기
    print("\n" + "=" * 60)
    print("처음 5개 항목 미리보기:")
    print("=" * 60)

    for idx, row in df.head(5).iterrows():
        print(f"\n[{idx+1}] {row['장']} - {row['조문번호']}")
        if row['항']:
            print(f"    항: ({row['항']})")
        print(f"    원문: {row['원문'][:100]}..." if len(row['원문']) > 100 else f"    원문: {row['원문']}")

    # 장별 통계
    print("\n" + "=" * 60)
    print("장별 조문 분포:")
    print("=" * 60)
    chapter_counts = df[df['장'] != '']['장'].value_counts().sort_index()
    for chapter, count in chapter_counts.items():
        print(f"  {chapter}: {count}개")

    # Excel 저장
    output_path = "DATA/output/구조화법률/중국/test_중국특허법.xlsx"
    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    from parsers.base import save_structured_to_excel
    save_structured_to_excel(df, output_path)

    print(f"\n💾 Excel 저장 완료: {output_path}")

except Exception as e:
    print(f"\n❌ 파싱 실패: {type(e).__name__}")
    print(f"에러 메시지: {str(e)}")
    import traceback
    print("\n상세 에러:")
    traceback.print_exc()

print("\n" + "=" * 60)
print("테스트 완료")
print("=" * 60)
