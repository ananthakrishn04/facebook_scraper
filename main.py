from fastapi import FastAPI, Query, HTTPException, BackgroundTasks, Request, Form, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional, Dict
import uvicorn
import os
import time
import json
from datetime import datetime
import random
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from fastapi.middleware.cors import CORSMiddleware

# Initialize FastAPI
app = FastAPI(
    title="Facebook Scraper",
    description="Facebook Page Scraper using Selenium",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

results_storage = {}

class ScrapeRequest(BaseModel):
    page_name: str
    posts_count: int = 5
    
class PostData(BaseModel):
    post_id: str
    text: Optional[str] = None
    post_url: Optional[str] = None
    time: Optional[str] = None
    image_urls: Optional[List[str]] = None
    likes: Optional[str] = None
    comments: Optional[str] = None
    shares: Optional[str] = None

class ScrapeResult(BaseModel):
    page_name: str
    timestamp: str
    posts: List[dict]

def get_chrome_options():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--lang=en-US")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36")
    return options

async def scrape_facebook_page(page_name: str, posts_count: int):
    try:
        task_id = f"{page_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        options = get_chrome_options()
        browser = webdriver.Chrome(options=options)

        url = f"https://www.facebook.com/{page_name}"
        browser.get(url)

        # Wait for page to initially load
        time.sleep(5)

        # Handle cookie consent if present
        try:
            cookies_button = WebDriverWait(browser, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Accept All')]"))
            )
            cookies_button.click()
            time.sleep(2)
        except (TimeoutException, NoSuchElementException):
            pass  
        
        close_button =  WebDriverWait(browser, 5).until(EC.element_to_be_clickable((By.XPATH, "//div[@aria-label='Close' and @role='button']")))
        close_button.click()


        posts = []
        scroll_count = 0
        max_scrolls = posts_count * 3  # Increase max scrolls to ensure we find enough posts
        processed_posts = set()
        
        # Initial scroll to trigger content loading
        browser.execute_script("window.scrollBy(0, 300);")
        time.sleep(2)
        
        while len(posts) < posts_count and scroll_count < max_scrolls:

            for _ in range(3):
                scroll_amount = random.randint(100, 300)
                browser.execute_script(f"window.scrollBy(0, {scroll_amount});")
                time.sleep(random.uniform(1, 2))
            
            scroll_count += 1
    
            try:
                WebDriverWait(browser, 5).until(
                    EC.presence_of_all_elements_located((By.XPATH, "//div[@role='article' and @aria-labelledby]"))
                )
            except:
                pass  # Continue even if timeout occurs
            
            # Find all post elements with the specific XPath
            post_elements = browser.find_elements(By.XPATH, "//div[@role='article' and @aria-labelledby]")
            print(f"Found {len(post_elements)} post elements")
            
            # If no elements found, try alternative selector
            if len(post_elements) == 0:
                post_elements = browser.find_elements(By.XPATH, "//div[@role='article' and not(ancestor::div[contains(@aria-label, 'Comment')])]")
                print(f"Using alternative selector, found {len(post_elements)} post elements")
            
            print(post_elements)

            # Process each post element
            for post_element in post_elements:
                if len(posts) >= posts_count:
                    break
                    
                try:
                    # Get a unique identifier for the post
                    post_id = post_element.get_attribute("aria-labelledby") or post_element.get_attribute("id")
                    
                    # If we couldn't get a reliable ID, create one from content
                    if not post_id:
                        # Create a composite fingerprint from content and position
                        text_content = post_element.text[:50]
                        location = post_element.location
                        post_id = f"{text_content}_{location['x']}_{location['y']}"
                    
                    # Skip if we've already processed this post
                    if post_id in processed_posts:
                        continue
                    
                    processed_posts.add(post_id)
                    
                    # Extract post text
                    text = ""
                    try:
                        # Try multiple selectors for text content
                        for selector in [
                            ".//div[contains(@data-ad-comet-preview, 'message')]",
                            ".//div[contains(@class, 'userContent')]",
                            ".//div[contains(@class, 'kvgmc6g5')]",
                            ".//div[contains(@class, 'ecm0bbzt')]"
                        ]:
                            text_elements = post_element.find_elements(By.XPATH, selector)
                            if text_elements:
                                text = "\n".join([el.text for el in text_elements if el.text])
                                if text:
                                    break
                        
                        # If still no text, try getting all text from the post
                        if not text:
                            text = post_element.text
                    except Exception as e:
                        print(f"Error extracting text: {e}")
                    
                    # Extract image URLs
                    image_urls = []
                    try:
                        # Try multiple selectors for images
                        for img_selector in [
                            ".//img[contains(@alt, 'Image')]",
                            ".//img[contains(@alt, 'May be')]",
                            ".//img[contains(@alt, 'Photo')]",
                            ".//img[not(contains(@alt, 'profile'))][@src]"
                        ]:
                            images = post_element.find_elements(By.XPATH, img_selector)
                            for img in images:
                                src = img.get_attribute("src")
                                if src and "http" in src and not any(url in src for url in ["emoji", "icon", "avatar", "profile"]):
                                    image_urls.append(src)
                        
                        # Remove duplicates
                        image_urls = list(set(image_urls))
                    except Exception as e:
                        print(f"Error extracting images: {e}")
                    
                    # Extract post URL
                    post_url = ""
                    try:
                        for url_selector in [
                            ".//a[contains(@href, '/posts/')]",
                            ".//a[contains(@href, '/photo/')]",
                            ".//a[contains(@href, '/permalink/')]",
                            ".//a[contains(@href, '/videos/')]"
                        ]:
                            url_elements = post_element.find_elements(By.XPATH, url_selector)
                            for url_element in url_elements:
                                potential_url = url_element.get_attribute("href")
                                if potential_url and "facebook.com" in potential_url:
                                    post_url = potential_url
                                    break
                            if post_url:
                                break
                    except Exception as e:
                        print(f"Error extracting post URL: {e}")
                    
                    # Extract post time
                    post_time = ""
                    try:
                        for time_selector in [
                            ".//a/span[contains(@class, 'timestamp')]",
                            ".//a/abbr",
                            ".//span[contains(@class, 'tojvnm2t')]",
                            ".//span[contains(@class, 'j1lvzwm4')]"
                        ]:
                            time_elements = post_element.find_elements(By.XPATH, time_selector)
                            for time_element in time_elements:
                                text = time_element.text
                                if text and any(time_word in text.lower() for time_word in ["hr", "min", "sec", "days", "yesterday", "today"]):
                                    post_time = text
                                    break
                            if post_time:
                                break
                    except Exception as e:
                        print(f"Error extracting post time: {e}")
                    
                    # Extract reactions
                    likes = comments = shares = ""
                    try:
                        # Try to find reaction elements
                        reaction_elements = post_element.find_elements(By.XPATH, 
                            ".//div[contains(@class, 'l9j0dhe7') or contains(@class, 'pcp91wgn')]//span")
                        
                        # Extract text from reaction elements
                        reaction_texts = [elem.text for elem in reaction_elements if elem.text]
                        
                        # Classify reactions based on text
                        for text in reaction_texts:
                            if any(c.isdigit() for c in text):
                                if "like" in text.lower() or "react" in text.lower():
                                    likes = text
                                elif "comment" in text.lower():
                                    comments = text
                                elif "share" in text.lower():
                                    shares = text
                                elif not likes:  # If no classification but has digits, assume likes
                                    likes = text
                    except Exception as e:
                        print(f"Error extracting reactions: {e}")
                    
                    # Create post data
                    post_data = {
                        "post_id": post_id,
                        "text": text,
                        "post_url": post_url,
                        "time": post_time,
                        "image_urls": image_urls,
                        "likes": likes,
                        "comments": comments,
                        "shares": shares
                    }
                    
                    posts.append(post_data)
                    print(f"Extracted post {len(posts)}/{posts_count}")
                    
                except Exception as e:
                    print(f"Error processing post: {e}")
            
            # If we found new posts, continue scrolling
            if len(posts) == 0 and scroll_count > 5:
                print("No posts found after multiple scrolls. Facebook might be blocking automated access.")
                break
        
        browser.quit()
        result = {
            "page_name": page_name,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "posts": posts
        }

        print(f"Successfully scraped {len(posts)} posts")
        
        results_storage[task_id] = result
        
        return task_id
    
    except Exception as e:
        print(f"Error scraping {page_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")
    
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """
    Home page with Facebook scraper interface
    """
    return templates.TemplateResponse("index.html", {"request": request, "results": results_storage})

@app.post("/scrape")
async def scrape_page(request: Request, background_tasks: BackgroundTasks, page_name: str = Form(...), posts_count: int = Form(5)):
    """
    Start scraping a Facebook page in the background
    """
    task_id = f"{page_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    background_tasks.add_task(scrape_facebook_page, page_name, posts_count)
    return RedirectResponse(url="/", status_code=303)

@app.get("/api/scrape", status_code=202)
async def api_scrape_page(request: ScrapeRequest, background_tasks: BackgroundTasks):
    """
    API endpoint to start scraping a Facebook page in the background
    """
    task_id = f"{request.page_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    background_tasks.add_task(scrape_facebook_page, request.page_name, request.posts_count)
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