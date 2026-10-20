"""테스트 공통 — 실제 LangSmith로 추적을 보내지 않는다.

app/main.py가 import 시점에 .env를 읽지만(load_dotenv), 이미 있는 환경변수는 덮어쓰지
않으므로 여기서 먼저 꺼 두면 테스트 실행이 LangSmith 프로젝트를 어지럽히지 않는다.
"""
import os

os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ.pop("ADMIN_TOKEN", None)
