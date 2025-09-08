import requests
from django.shortcuts import render
from django.conf import settings

# 로컬 테스트용
# import os
# from dotenv import load_dotenv
# load_dotenv()

# Create your views here.
def index(request):
    # FastAPI 서버 주소
    # 로컬 테스트용
    # fastapi_url = os.environ.get("FASTAPI_URL") + "/chatbot/"
    fastapi_url = f"{settings.FASTAPI_URL}/chatbot/"

    try:
        response = requests.get(fastapi_url, timeout=5)
        data = response.json()
        chatbot_list = data.get("chatbot", [])
    except Exception as e:
        chatbot_list = [f"Error: {e}"]

    return render(request, "app/index.html", {"chatbot_list": chatbot_list})
