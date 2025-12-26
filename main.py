import requests
import time
import unicodedata
import re
import os
from datetime import datetime
from typing import Optional, Tuple, List, Dict
import json
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import threading
from queue import Queue
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- CONFIGURATION ---
ACCOUNT_NAME = "bemolfarma"
VTEX_COOKIE = os.getenv("VTEX_COOKIE", "PASTE_YOUR_COOKIE_HERE")

# URLs
BASE_URL = f"https://{ACCOUNT_NAME}.vtexcommercestable.com.br/api/catalog/pvt"
CATALOG_SYSTEM_URL = f"https://{ACCOUNT_NAME}.vtexcommercestable.com.br/api/catalog_system/pvt"
LOG_FILE = "execution_log.txt"
ERROR_LOG = "error_log.txt"
CHECKPOINT_FILE = "checkpoint.json"

HEADERS = {
    "VtexIdclientAutCookie": VTEX_COOKIE,
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# --- PERFORMANCE AND SECURITY CONFIGURATION ---
MAX_WORKERS = 3  # Parallel threads (adjust as needed)
REQUEST_TIMEOUT = 30  # Timeout in seconds
MAX_RETRIES = 3  # Retry attempts
BACKOFF_FACTOR = 1  # Exponential backoff factor
RATE_LIMIT_DELAY = 0.3  # Delay between requests (seconds)
CHECKPOINT_INTERVAL = 10  # Save checkpoint every N SKUs

# Lock for thread-safe writing to files
log_lock = threading.Lock()

# --- SESSION WITH AUTOMATIC RETRY ---
def create_session() -> requests.Session:
    """
    Creates a session with automatic retry to handle temporary failures.
    """
    session = requests.Session()
    
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=[429, 500, 502, 503, 504],  # Rate limit and server errors
        allowed_methods=["GET", "PUT", "POST"]
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    return session

# Reusable global session
SESSION = create_session()

# --- UTILS ---
def log_message(message: str, level: str = "INFO"):
    """Thread-safe logging with severity levels."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] [{level}] {message}"
    
    with log_lock:
        print(formatted_msg)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(formatted_msg + "\n")
            
            # Errors go to a separate file
            if level in ["ERROR", "CRITICAL"]:
                with open(ERROR_LOG, "a", encoding="utf-8") as f:
                    f.write(formatted_msg + "\n")
        except Exception as e:
            print(f"Error writing log: {e}")

def slugify(text: str) -> str:
    """Generates URL-friendly slug."""
    if not text:
        return ""
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = text.lower().strip()
    text = re.sub(r'[\s]+', '-', text)
    text = re.sub(r'[^a-z0-9\-]', '', text)
    return text

# --- CHECKPOINT SYSTEM ---
class CheckpointManager:
    """Manages checkpoints to resume processing."""
    
    def __init__(self, filename: str = CHECKPOINT_FILE):
        self.filename = filename
        self.data = self.load()
    
    def load(self) -> Dict:
        """Loads existing checkpoint."""
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    return json.load(f)
            except:
                return {"processed_skus": [], "last_page": 1}
        return {"processed_skus": [], "last_page": 1}
    
    def save(self):
        """Saves checkpoint."""
        with log_lock:
            try:
                with open(self.filename, 'w') as f:
                    json.dump(self.data, f)
            except Exception as e:
                log_message(f"Error saving checkpoint: {e}", "ERROR")
    
    def mark_processed(self, sku_id: int):
        """Marks SKU as processed."""
        if sku_id not in self.data["processed_skus"]:
            self.data["processed_skus"].append(sku_id)
    
    def is_processed(self, sku_id: int) -> bool:
        """Checks if SKU has already been processed."""
        return sku_id in self.data["processed_skus"]
    
    def update_page(self, page: int):
        """Updates the last processed page."""
        self.data["last_page"] = page
    
    def clear(self):
        """Clears checkpoint."""
        self.data = {"processed_skus": [], "last_page": 1}
        self.save()

# --- RATE LIMITER ---
class RateLimiter:
    """Controls request rate."""
    
    def __init__(self, delay: float = RATE_LIMIT_DELAY):
        self.delay = delay
        self.last_request = 0
        self.lock = threading.Lock()
    
    def wait(self):
        """Waits before making the next request."""
        with self.lock:
            elapsed = time.time() - self.last_request
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)
            self.last_request = time.time()

rate_limiter = RateLimiter()

# --- API FUNCTIONS ---
def safe_request(method: str, url: str, **kwargs) -> Optional[requests.Response]:
    """
    Makes a request with rate limiting, timeout, and error handling.
    """
    rate_limiter.wait()
    
    try:
        kwargs.setdefault('timeout', REQUEST_TIMEOUT)
        kwargs.setdefault('headers', HEADERS)
        
        response = SESSION.request(method, url, **kwargs)
        
        # Specific rate limit handling
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 60))
            log_message(f"Rate limit hit. Waiting {retry_after}s...", "WARNING")
            time.sleep(retry_after)
            return safe_request(method, url, **kwargs)  # Retry
        
        return response
        
    except requests.exceptions.Timeout:
        log_message(f"Timeout on {method} {url}", "ERROR")
        return None
    except requests.exceptions.ConnectionError as e:
        log_message(f"Connection error: {e}", "ERROR")
        return None
    except Exception as e:
        log_message(f"Unexpected error: {e}", "ERROR")
        return None

def update_image_alt(sku_id: int, original_image_data: Dict, new_alt_text: str) -> bool:
    """Updates the image alt text."""
    file_id = original_image_data.get('Id')
    url = f"{BASE_URL}/stockkeepingunit/{sku_id}/file/{file_id}"
    
    payload = original_image_data.copy()
    payload["Label"] = new_alt_text
    payload["Text"] = new_alt_text
    
    response = safe_request('PUT', url, json=payload)
    
    if response and response.status_code == 200:
        log_message(f"      [OK] Image updated: '{new_alt_text}'")
        return True
    elif response and response.status_code == 401:
        log_message(f"      [AUTH ERROR] Cookie expired.", "CRITICAL")
        return False
    else:
        error_msg = response.text if response else "No response"
        log_message(f"      [UPDATE ERROR] SKU {sku_id}: {error_msg}", "ERROR")
        return False

def process_sku_images(sku_id: int, product_name: str) -> bool:
    """Processes all images for a SKU."""
    url_get = f"{BASE_URL}/stockkeepingunit/{sku_id}/file"
    
    response = safe_request('GET', url_get)
    
    if not response:
        return False
    
    if response.status_code == 200:
        images = response.json()
        
        if not images:
            return True

        # Checks if ALL images already have alt text
        all_have_alt = all(
            img.get('Label') and img.get('Label').strip() 
            for img in images
        )
        
        if all_have_alt:
            log_message(f"      [SKIP SKU] All images already have alt text - SKU {sku_id}")
            return True

        base_name = slugify(product_name)
        success = True

        for index, img in enumerate(images, start=1):
            current_label = img.get('Label', '')
            new_alt = f"{base_name}_{index}"
            
            if current_label != new_alt:
                if not update_image_alt(sku_id, img, new_alt):
                    success = False
            else:
                log_message(f"      [SKIP] Already correct: {new_alt}")
        
        return success
    
    elif response.status_code == 404:
        return True
    else:
        log_message(f"[GET ERROR] SKU {sku_id} - Status: {response.status_code}", "ERROR")
        return False

def get_sku_details(sku_id: int) -> Tuple[Optional[str], Optional[str]]:
    """Retrieves SKU details."""
    url = f"{BASE_URL}/stockkeepingunit/{sku_id}"
    
    response = safe_request('GET', url)
    
    if response and response.status_code == 200:
        data = response.json()
        name = data.get('ProductName') or data.get('NameComplete') or data.get('Name')
        ref_id = data.get('RefId')
        return name, ref_id
    
    return None, None

def process_single_sku(sku_id: int, checkpoint: CheckpointManager) -> bool:
    """Processes a single SKU."""
    if checkpoint.is_processed(sku_id):
        log_message(f"SKU {sku_id} already processed (checkpoint)", "INFO")
        return True
    
    product_name, ref_id = get_sku_details(sku_id)
    
    if product_name:
        log_message(f"SKU ID: {sku_id} | RefId: {ref_id} | Product: {product_name}")
        success = process_sku_images(sku_id, product_name)
        
        if success:
            checkpoint.mark_processed(sku_id)
        
        return success
    else:
        log_message(f"SKU ID: {sku_id} | Ignored (no details)", "WARNING")
        return True

# --- RUNNER ---
def run_bulk_update(resume: bool = True):
    """Executes bulk update with parallel processing."""
    checkpoint = CheckpointManager()
    
    if not resume:
        checkpoint.clear()
        log_message("Starting fresh (checkpoint cleared)")
    
    start_page = checkpoint.data["last_page"]
    page_size = 50
    
    log_message(f"--- STARTING BEMOL FARMA UPDATE (ROBUST VERSION) ---")
    log_message(f"Max workers: {MAX_WORKERS} | Starting from page: {start_page}")
    
    page = start_page
    processed_count = 0

    try:
        while True:
            url_list = f"{CATALOG_SYSTEM_URL}/sku/stockkeepingunitids?page={page}&pagesize={page_size}"
            
            response = safe_request('GET', url_list)
            
            if not response:
                log_message(f"Failed to fetch page {page}", "ERROR")
                break
            
            if response.status_code == 200:
                sku_ids = response.json()
                
                if not sku_ids:
                    log_message("End of catalog reached.")
                    break
                
                log_message(f"\n--- Processing Page {page} ({len(sku_ids)} SKUs) ---")
                
                # Parallel processing with ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    futures = {
                        executor.submit(process_single_sku, sku_id, checkpoint): sku_id 
                        for sku_id in sku_ids
                    }
                    
                    for future in as_completed(futures):
                        processed_count += 1
                        
                        # Save checkpoint periodically
                        if processed_count % CHECKPOINT_INTERVAL == 0:
                            checkpoint.save()
                            log_message(f"Checkpoint saved ({processed_count} SKUs processed)")
                
                checkpoint.update_page(page + 1)
                checkpoint.save()
                page += 1

            elif response.status_code == 401:
                log_message("CRITICAL: Cookie expired.", "CRITICAL")
                break
            else:
                log_message(f"Error on page {page}. Status: {response.status_code}", "ERROR")
                break
    
    except KeyboardInterrupt:
        log_message("Process interrupted by user. Saving checkpoint...", "WARNING")
        checkpoint.save()
    except Exception as e:
        log_message(f"Fatal Error: {e}", "CRITICAL")
        checkpoint.save()
    
    log_message(f"--- PROCESS COMPLETED ({processed_count} SKUs processed) ---")

# --- MAIN ---
if __name__ == "__main__":
    if "PASTE_YOUR_COOKIE_HERE" in VTEX_COOKIE:
        print("⚠️ ALERT: Paste your cookie in the VTEX_COOKIE variable.")
    else:
        print("=" * 60)
        print("VTEX IMAGE ALT TEXT UPDATER - ROBUST VERSION")
        print("=" * 60)
        print(f"Max Workers: {MAX_WORKERS}")
        print(f"Rate Limit Delay: {RATE_LIMIT_DELAY}s")
        print(f"Request Timeout: {REQUEST_TIMEOUT}s")
        print("=" * 60)
        
        resume = input("Resume from checkpoint? (Y/n): ").strip().lower() != 'n'
        confirm = input("Type 'YES' to start: ")
        
        if confirm == "YES":
            run_bulk_update(resume=resume)