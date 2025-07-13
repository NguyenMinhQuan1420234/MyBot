import logging
import subprocess

class MCPPlaywrightAgent:
    def __init__(self):
        # Default settings for Playwright MCP
        self.command = ["npx", "@playwright/mcp@latest"]

    def run_command(self, user_command):
        try:
            # Run MCP Playwright with user command as argument
            full_cmd = self.command + [user_command]
            logging.info(f"Running MCP Playwright: {' '.join(full_cmd)}")
            result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                logging.info(f"MCP Playwright output: {result.stdout}")
                return result.stdout
            else:
                logging.error(f"MCP Playwright error: {result.stderr}")
                return f"Error: {result.stderr}"
        except Exception as e:
            logging.error(f"Exception running MCP Playwright: {e}")
            return f"Exception: {e}"
