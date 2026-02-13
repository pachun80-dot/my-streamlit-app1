"""기존 import 호환성 유지를 위한 래퍼 모듈.

모든 파싱 로직은 parsers/ 패키지로 이동되었다.
이 파일은 기존 import문 (app.py, test_*.py 등)이 깨지지 않도록
parsers 패키지의 공개 API를 re-export한다.
"""

from parsers import (
    split_articles,
    extract_structured_articles,
    _detect_lang,
    _detect_format,
)
from parsers.base import (
    parse_pdf,
    parse_rtf,
    save_structured_to_excel,
)
from parsers.germany import (
    parse_german_xml,
    extract_structured_articles_from_xml,
)
