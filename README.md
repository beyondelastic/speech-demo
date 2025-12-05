# Speech Demo - Local Browser Control API

## Overview

This is a local FastAPI web application designed to work with Microsoft Foundry voice agents. It provides endpoints that enable a voice-controlled agent to open browser windows on your local machine through voice commands.

## Purpose

This API serves as a tool configuration for a Microsoft Foundry voice agent deployment. When the agent receives a voice command to open a browser or navigate to a URL, it can invoke the local `/api/open-browser` endpoint to execute the action on your machine.

### Use Case
- **Voice Agent**: A Microsoft Foundry voice agent receives audio input from a user
- **Command Recognition**: The agent interprets voice commands to open browsers or navigate to URLs
- **API Call**: The agent makes an HTTP GET request to this local API
- **Local Execution**: Your local machine opens the requested URL in the default browser

## Features

- **FastAPI Server**: Lightweight and fast REST API running on `http://localhost:8000`
- **Browser Control Endpoint**: Open any URL in your default browser via API call
- **Health Check**: Monitor server status with the health endpoint
- **Error Handling**: Gracefully handles systems without graphical browsers
- **Logging**: All requests are logged for debugging and monitoring

## Endpoints

### GET `/`
Returns the welcome HTML page.

**Response**: HTML welcome page

---

### GET `/api/health`
Health check endpoint to verify the server is running.

**Response**:
```json
{
  "status": "healthy",
  "message": "Server is running"
}
```

---

### GET `/api/open-browser`
Opens a URL in the local default browser.

**Query Parameters**:
- `url` (optional, default: `http://localhost:8000`): The URL to open in the browser

**Example Requests**:
```bash
# Open the default server URL
http://localhost:8000/api/open-browser

# Open a specific URL
http://localhost:8000/api/open-browser?url=https://www.example.com

# Open a local file or service
http://localhost:8000/api/open-browser?url=http://192.168.1.100:3000
```

**Response**:
```json
{
  "status": "success",
  "message": "Browser window opened",
  "url_opened": "https://www.example.com",
  "timestamp": 1733354400.123
}
```

## Installation

### Prerequisites
- Python 3.8 or higher
- A default browser installed on your system (Firefox, Chrome, Chromium, etc.)

### Setup

1. **Clone or navigate to the project**:
```bash
cd /home/aullah/git/speech-demo
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

## Running the Server

Start the server from the terminal:

```bash
python main.py
```

**Expected Output**:
```
Starting FastAPI server at http://127.0.0.1:8000
Opening browser...
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete [uvicorn]
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

The application will:
1. Start the FastAPI server on `http://127.0.0.1:8000`
2. Automatically open your default browser to the welcome page
3. Display server logs in the terminal

## Exposing the Local API to the Cloud

If you're running this application on your local machine (laptop), you need to expose it to the internet so that your Microsoft Foundry voice agent can access it. **devtunnel** is a convenient tool for creating a secure tunnel to your local API.

### Using devtunnel

devtunnel creates a publicly accessible URL that tunnels to your local service. This allows cloud-based agents to reach your local API.

#### Prerequisites
- Install devtunnel: Follow instructions at https://learn.microsoft.com/en-us/azure/developer/dev-tunnels/overview

#### Setup Steps

1. **Authenticate with Microsoft Account**:
```bash
devtunnel user login
```

2. **Create a tunnel**:
```bash
devtunnel create mytunnelname -a
```
Replace `mytunnelname` with your preferred tunnel name (e.g., `speech-demo-tunnel`)

3. **Create a port mapping** (for port 8000):
```bash
devtunnel port create mytunnelname -p 8000
```

4. **Start hosting the tunnel**:
```bash
devtunnel host mytunnelname
```

#### Example Output

After running these commands, you'll get output similar to:
```
Tunnel 'speech-demo-tunnel' is now active. You can access it from:
Connect via browser: https://speech-demo-tunnel-xxx.devtunnels.ms
```

#### Using the Public URL

Once devtunnel is running, your API endpoints are accessible at:
- Main page: `https://speech-demo-tunnel-xxx.devtunnels.ms/`
- Health check: `https://speech-demo-tunnel-xxx.devtunnels.ms/api/health`
- Open browser: `https://speech-demo-tunnel-xxx.devtunnels.ms/api/open-browser?url=https://example.com`

### Workflow

1. Start your local FastAPI server: `python main.py`
2. In a separate terminal, start devtunnel: `devtunnel host mytunnelname`
3. Copy the public URL from devtunnel output
4. Configure this public URL in your Microsoft Foundry voice agent tool settings
5. Your voice agent can now call the endpoint from the cloud

## Microsoft Foundry Voice Agent Integration

### Tool Configuration

When configuring this API as a tool in your Microsoft Foundry voice agent deployment:

1. **OpenAPI Schema**: This project includes an `openapi.json` file that defines the API specification. This schema is used by the Foundry agent to understand and invoke the available endpoints.

2. **Update the Server URL**: Before importing the OpenAPI schema into your Foundry agent tool configuration, you must update the server URL in `openapi.json`:

```json
"servers": [
  {
    "url": "https://your-devtunnel-url:8000/"
  }
]
```

Replace `your-devtunnel-url` with the actual devtunnel URL you created (e.g., `https://speech-demo-tunnel-abc123.devtunnels.ms`).

3. **Import to Foundry**: Use the updated `openapi.json` file to configure the tool in your Microsoft Foundry agent. This allows the agent to:
   - Understand the available endpoints
   - Know what parameters each endpoint accepts
   - Properly format requests to your local API

### Example Agent Configuration

In your agent's tool definitions, reference the OpenAPI schema:

1. **Tool Name**: `open_browser` or `open_local_browser`
2. **Endpoint**: `http://localhost:8000/api/open-browser`
3. **Method**: GET
4. **Parameters**:
   - `url` (string, optional): The URL to open

### Example Agent Configuration

In your agent's tool definitions, you would configure something like:

```json
{
  "name": "open_browser",
  "description": "Opens a URL in the local browser window",
  "endpoint": "http://localhost:8000/api/open-browser",
  "parameters": {
    "url": {
      "type": "string",
      "description": "The URL to open in the browser",
      "required": false,
      "default": "http://localhost:8000"
    }
  }
}
```

## Voice Command Examples

Once integrated with your Microsoft Foundry voice agent, you could use voice commands like:

- "Open the local browser"

The agent will interpret these commands and call the `/api/open-browser` endpoint with the appropriate URL.

## Troubleshooting

### Browser Not Opening

If you see messages like "no method available for opening", it means no graphical browser is installed:

**On Linux (Debian/Ubuntu)**:
```bash
# Install Firefox
sudo apt-get install firefox

# Or install Chromium
sudo apt-get install chromium-browser
```

**On macOS**:
Browsers are typically pre-installed. If issues persist, ensure Safari or Chrome are available.

**On Windows**:
Browsers are typically pre-installed. If issues persist, ensure Edge, Chrome, or Firefox are available.

### Port Already in Use

If port 8000 is already in use, you can modify the port in `main.py`:

```python
if __name__ == "__main__":
    host = "127.0.0.1"
    port = 8001  # Change to a different port
```

### Server Connection Issues

Ensure the server is running and accessible:

```bash
curl http://localhost:8000/api/health
```

## Project Structure

```
speech-demo/
├── main.py              # FastAPI application
├── requirements.txt     # Python dependencies
└── README.md           # This file
```

## Dependencies

- **fastapi**: Web framework for building APIs
- **uvicorn**: ASGI server for running FastAPI
- **python-multipart**: Support for form data parsing

See `requirements.txt` for specific versions.

## License

This project is part of the speech-demo repository.

## Support

For issues or questions, please refer to the main project documentation or contact the development team.
