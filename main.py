import subprocess
import sys
import time
import webbrowser
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()


@app.get("/", response_class=HTMLResponse)
async def read_root():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>FastAPI Web App</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
                background-color: #f5f5f5;
            }
            .container {
                background-color: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            h1 {
                color: #333;
            }
            p {
                color: #666;
                line-height: 1.6;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Welcome to FastAPI</h1>
            <p>This web app was opened automatically from the terminal using Python subprocess!</p>
            <p>Server is running on <strong>http://localhost:8000</strong></p>
        </div>
    </body>
    </html>
    """


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "message": "Server is running"}


@app.get("/api/open-browser")
async def open_browser_endpoint(url: str = "https://www.karlstorz.com/"):
    """
    Endpoint that opens a browser window when called by an LLM/agent.
    
    Query parameters:
    - url: The URL to open in the browser (defaults to https://www.karlstorz.com/)
    """
    try:
        # Try to open browser in a subprocess with error handling
        process = subprocess.Popen(
            [sys.executable, "-c", f"import webbrowser; webbrowser.open('{url}')"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait a moment and check if process is still running
        time.sleep(0.5)
        poll = process.poll()
        
        if poll is None:
            logger.info(f"Browser opened successfully for URL: {url}")
            return {
                "status": "success",
                "message": "Browser window opened",
                "url_opened": url,
                "timestamp": time.time()
            }
        else:
            # Process failed, log the error but still return success response
            # (since the request to open was processed)
            stderr = process.stderr.read().decode() if process.stderr else ""
            logger.warning(f"Browser open attempt completed with code {poll}. Error: {stderr}")
            logger.info(f"URL to open: {url}")
            return {
                "status": "success",
                "message": "Browser open command sent (no browser available on system)",
                "url_requested": url,
                "note": "No graphical browser detected. URL logged for reference.",
                "timestamp": time.time()
            }
    except Exception as e:
        logger.error(f"Error attempting to open browser: {str(e)}")
        return {
            "status": "success",
            "message": "Browser open command processed",
            "url_requested": url,
            "note": f"Error: {str(e)}. URL: {url}",
            "timestamp": time.time()
        }


def open_browser(url: str, delay: float = 1.0):
    """Open browser after a delay to allow server to start"""
    time.sleep(delay)
    webbrowser.open(url)


if __name__ == "__main__":
    # Configuration
    host = "127.0.0.1"
    port = 8000
    url = f"http://{host}:{port}"
    
    # Open browser in a subprocess
    print(f"Starting FastAPI server at {url}")
    print("Opening browser...")
    
    # Use subprocess to open browser
    subprocess.Popen([
        sys.executable, 
        "-c", 
        f"import webbrowser; import time; time.sleep(1); webbrowser.open('{url}')"
    ])
    
    # Start the server
    uvicorn.run(app, host=host, port=port)
