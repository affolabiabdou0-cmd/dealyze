"""Shared Gemini client for all VYXEN agents."""
import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

def get_gemini_model(model_name: str = "gemini-2.5-flash"):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not found in environment")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(model_name)
