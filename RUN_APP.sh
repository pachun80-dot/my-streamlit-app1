#!/bin/bash
# 법령 번역 비교 분석 시스템 실행 스크립트

cd "$(dirname "$0")"

echo "🚀 Streamlit 앱 실행 중..."
echo "📍 브라우저에서 http://localhost:8501 열림"
echo ""
echo "✅ 3탭 구조:"
echo "  1. 📊 법령 구조화 (PDF → 엑셀)"
echo "  2. 🔍 번역 실행 (엑셀 → 번역 + 매칭)"
echo "  3. 📋 번역결과 상세보기"
echo ""
echo "❌ 종료: Ctrl+C"
echo ""

streamlit run app.py
