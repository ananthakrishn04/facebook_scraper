from fastapi import FastAPI, Query, HTTPException, BackgroundTasks, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, HttpUrl
from typing import List, Optional
import facebook_scraper as fs
import uvicorn
import os
from datetime import datetime
import json
from fastapi.middleware.cors import CORSMiddleware

# Initialize FastAPI
app = FastAPI(
    title="Facebook Scraper API",
    description="API for scraping public Facebook pages",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up templates and static files
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Data models
class ScrapeRequest(BaseModel):
    page_name: str
    posts_count: int = 5
    cookies_file: Optional[str] = None
    
class PostData(BaseModel):
    post_id: str
    text: Optional[str] = None
    post_url: Optional[str] = None
    time: Optional[datetime] = None
    image_url: Optional[List[str]] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None

class ScrapeResult(BaseModel):
    page_name: str
    timestamp: datetime
    posts: List[PostData]

# Storage for scrape results
results_storage = {}

# Scraper functionality
async def scrape_facebook_page(page_name: str, posts_count: int, cookies_file: Optional[str] = None):
    try:
        # Login if cookies are provided
        if cookies_file and os.path.exists(cookies_file):
            fs.set_cookies(cookies_file)
        
        # Get posts
        posts = []
        for post in fs.get_posts(page_name, pages=posts_count):
            posts.append(
                PostData(
                    post_id=post.get('post_id', ''),
                    text=post.get('text', ''),
                    post_url=post.get('post_url', ''),
                    time=post.get('time', datetime.now()),
                    image_url=post.get('images', []),
                    likes=post.get('likes', 0),
                    comments=post.get('comments', 0),
                    shares=post.get('shares', 0)
                )
            )
        
        # Store result
        result = ScrapeResult(
            page_name=page_name,
            timestamp=datetime.now(),
            posts=posts
        )
        
        # Save result to storage
        task_id = f"{page_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        results_storage[task_id] = result
        
        return task_id
    
    except Exception as e:
        print(f"Error scraping {page_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")

# Home page route
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """
    Home page with Facebook scraper interface
    """
    return templates.TemplateResponse("index.html", {"request": request, "results": results_storage})

# API Endpoints
@app.post("/scrape")
async def scrape_page(request: Request, background_tasks: BackgroundTasks, page_name: str = Form(...), posts_count: int = Form(5)):
    """
    Start scraping a Facebook page in the background
    """
    task_id = f"{page_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    background_tasks.add_task(scrape_facebook_page, page_name, posts_count, None)
    return RedirectResponse(url="/", status_code=303)

@app.get("/api/scrape", status_code=202)
async def api_scrape_page(request: ScrapeRequest, background_tasks: BackgroundTasks):
    """
    API endpoint to start scraping a Facebook page in the background
    """
    task_id = f"{request.page_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    background_tasks.add_task(scrape_facebook_page, request.page_name, request.posts_count, request.cookies_file)
    return {"task_id": task_id, "status": "Processing", "message": f"Scraping started for {request.page_name}"}

@app.get("/results/{task_id}", response_class=HTMLResponse)
async def view_result(request: Request, task_id: str):
    """
    View a specific result
    """
    if task_id in results_storage:
        return templates.TemplateResponse(
            "result_detail.html", 
            {"request": request, "task_id": task_id, "result": results_storage[task_id]}
        )
    else:
        return templates.TemplateResponse(
            "error.html", 
            {"request": request, "message": f"Result {task_id} not found"}
        )

@app.get("/api/results/{task_id}")
async def get_results(task_id: str):
    """
    API endpoint to get the results of a scraping task
    """
    if task_id in results_storage:
        return results_storage[task_id]
    else:
        # Check if the task is still processing
        page_name = task_id.split('_')[0]
        for tid in results_storage:
            if tid.startswith(page_name):
                return {"status": "Not found", "message": f"Task {task_id} not found, but another task for {page_name} exists"}
        
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

@app.get("/api/results")
async def list_results():
    """
    API endpoint to list all available results
    """
    return {"available_results": list(results_storage.keys())}

@app.delete("/results/{task_id}")
async def delete_result(request: Request, task_id: str):
    """
    Delete a specific result and redirect to home page
    """
    if task_id in results_storage:
        del results_storage[task_id]
        return RedirectResponse(url="/", status_code=303)
    else:
        return templates.TemplateResponse(
            "error.html", 
            {"request": request, "message": f"Result {task_id} not found"}
        )

@app.delete("/api/results/{task_id}")
async def api_delete_result(task_id: str):
    """
    API endpoint to delete a specific result
    """
    if task_id in results_storage:
        del results_storage[task_id]
        return {"status": "Deleted", "message": f"Result {task_id} deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

# Run the app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)