"""Run the Opportunity Radar local web app with its on-demand search API."""

import uvicorn


if __name__ == "__main__":
    uvicorn.run("api.server:app", host="127.0.0.1", port=8000, reload=False)
