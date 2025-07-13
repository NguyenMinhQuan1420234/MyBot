import google.generativeai as genai
import logging
from mcp_playwright_agent import MCPPlaywrightAgent

class Agent:
    def __init__(self, gemini_api_key):
        genai.configure(api_key=gemini_api_key)
        self.model = genai.GenerativeModel('models/gemini-2.0-flash-exp')
        self.mcp_agent = MCPPlaywrightAgent()

    def ask_gemini(self, prompt):
        response = self.model.generate_content(prompt)
        logging.info(f"GeminiAI Request: {prompt}")
        logging.info(f"GeminiAI Response: {response.text if hasattr(response, 'text') else str(response)}")
        return response.text if hasattr(response, 'text') else str(response)

    def run_playwright(self, command):
        logging.info(f"Playwright Command: {command}")
        return self.mcp_agent.run_command(command)
