# 법령 번역 비교 분석 시스템

다국어 특허법을 구조화하고 AI 번역을 비교 분석하는 웹 애플리케이션

## 주요 기능

### 1. 법령 구조화
- PDF/XML 파일에서 법령 조문을 자동 추출
- 계층 구조(편/장/절/조/항/호/목) 분석
- Excel 파일로 구조화 저장

### 2. AI 번역
- Gemini & Claude 동시 번역
- 조문 단위 번역 비교
- 번역 차이점 자동 분석

### 3. 한국법 매칭
- AI 기반 유사 조문 자동 매칭
- 매칭 이유 설명 제공
- 일괄 매칭으로 빠른 처리

## 지원 국가/형식

### PDF 지원
- 유럽 (EPC)
- 홍콩
- 대만
- 뉴질랜드
- 한국

### XML 지원
- 독일 특허법

## 프로젝트 구조

```
법령홈페이지/
├── app.py              # 메인 Streamlit 앱
├── pdf_parser.py       # PDF/XML 파싱 로직
├── translator.py       # AI 번역 로직
├── embedder.py         # 한국법 매칭 로직
├── RUN_APP.sh          # 앱 실행 스크립트
├── requirements.txt    # 필수 패키지
└── DATA/
    ├── [COUNTRY]/      # 국가별 원본 파일
    └── output/
        ├── 구조화법률/     # 구조화된 Excel 파일
        └── 번역비교결과/   # 번역 비교 결과
```

## 설치 및 실행

### 1. 패키지 설치
```bash
pip install -r requirements.txt
```

### 2. API 키 설정
`.streamlit/secrets.toml` 파일 생성:
```toml
ANTHROPIC_API_KEY = "your-claude-api-key"
GOOGLE_API_KEY = "your-gemini-api-key"
```

### 3. 앱 실행
```bash
./RUN_APP.sh
# 또는
streamlit run app.py
```

## 사용 방법

1. **법령 구조화**: 국가 선택 → PDF/XML 업로드 → 구조화 실행
2. **번역 비교**: 외국법 선택 → 한국법 선택 → 번역 서비스 선택 → 실행
3. **결과 확인**: 상세보기로 조문별 비교 → Excel 다운로드

## 기술 스택

- **Frontend**: Streamlit
- **PDF Parsing**: pdfplumber
- **XML Parsing**: lxml
- **AI**: Claude Sonnet 4.5, Gemini 2.0 Flash
- **Data Processing**: pandas, openpyxl

## 주요 특징

### 법령 구조 처리
- 한국법: 편/장/절/조/항/호/목
- 유럽법: Part/Chapter/Section/Article/Paragraph/(a)(b)(c)
- 독일법: Abschnitt/§/Absatz/1./2./3.

### 번역 방식
- 조문 단위 그룹화 번역
- 항/호 번호 자동 포함
- 병렬 처리로 속도 최적화

### 매칭 알고리즘
- AI 기반 의미론적 매칭
- 일괄 API 호출로 효율성 향상
- 조문 제목 + 내용 복합 분석
