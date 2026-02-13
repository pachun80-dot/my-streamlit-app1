"""일본 법령 파서 통합 테스트"""

from japan_parser import parse_japan_html_to_dataframe
import pandas as pd
import os
from parsers.base import save_structured_to_excel

# 테스트 파일 경로
test_files = {
    "특허법": "/Users/yunseok/Downloads/334AC0000000121_20250601_504AC0000000068.html",
    "상표법": "/Users/yunseok/Downloads/334AC0000000127_20250601_504AC0000000068.html",
    "디자인보호법": "/Users/yunseok/Downloads/334AC0000000125_20250601_504AC0000000068.html"
}

print("=" * 70)
print("일본 법령 파서 통합 테스트")
print("=" * 70)

for law_name, file_path in test_files.items():
    if not os.path.exists(file_path):
        print(f"\n⚠️  {law_name} 파일을 찾을 수 없습니다: {file_path}")
        continue

    print(f"\n{'=' * 70}")
    print(f"📖 {law_name} 테스트")
    print("=" * 70)

    try:
        df = parse_japan_html_to_dataframe(file_path)

        print(f"\n✅ 파싱 성공! 총 항목 수: {len(df)}")

        # 통계
        print(f"\n📊 통계:")
        print(f"  - 총 항목: {len(df)}")
        print(f"  - 本文: {len(df[df['편'] == ''])}")
        print(f"  - 附則: {len(df[df['편'] == '附則'])}")
        print(f"  - 章: {len(df[df['장'] != ''])}")
        print(f"  - 節: {len(df[df['절'] != ''])}")

        # 節이 있으면서 章도 있는 항목 확인
        sections_with_chapter = df[
            (df['절'].notna()) & (df['절'] != '') &
            (df['장'].notna()) & (df['장'] != '')
        ]
        if len(sections_with_chapter) > 0:
            print(f"  - 節+章 함께: {len(sections_with_chapter)} (100%)")

        # Excel 저장
        output_path = f"DATA/output/구조화법률/일본/일본{law_name}_최종.xlsx"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        save_structured_to_excel(df, output_path)
        print(f"\n💾 Excel 저장: {output_path}")

    except Exception as e:
        print(f"\n❌ 에러: {type(e).__name__}")
        print(f"메시지: {str(e)}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 70)
print("✅ 모든 테스트 완료!")
print("=" * 70)
