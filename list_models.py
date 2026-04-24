import os
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

# Configure the API
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# List available models
print("Available Gemini models:")
for model in genai.list_models():
    print(f"- {model.name}")