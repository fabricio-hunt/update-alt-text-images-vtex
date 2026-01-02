# VTEX Image Alt Text Bulk Updater

A robust, multi-threaded Python utility designed to automate the process of updating image labels (Alt Text) for SKUs on the VTEX e-commerce platform.

This script fetches SKUs from the catalog, generates SEO-friendly slugs based on the product name (e.g., `product-name-1`), and updates the image labels if they do not match the expected pattern.

##  Key Features

* **Concurrency:** Uses `ThreadPoolExecutor` to process multiple SKUs in parallel, significantly reducing execution time.
* **Resilience:** Implements a robust `Retry` strategy with exponential backoff for handling network instability and API Rate Limits (HTTP 429).
* **Checkpoint System:** automatically saves progress to `checkpoint.json`. You can stop the script and resume exactly where you left off.
* **SEO Optimization:** automatically converts product names into URL-friendly slugs (e.g., "Vitamin C 500mg" -> "vitamin-c-500mg").
* **Smart Logging:** Thread-safe logging to both console and files (`execution_log.txt` for info, `error_log.txt` for errors).
* **Safety Checks:** Verifies if images already have the correct tag to avoid unnecessary API calls.

##  Prerequisites

* **Python 3.8+**
* **Git**

##  Installation

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/your-username/vtex-image-updater.git](https://github.com/your-username/vtex-image-updater.git)
    cd vtex-image-updater
    ```

2.  **Create a Virtual Environment (Recommended):**
    ```bash
    # Windows
    python -m venv venv
    .\venv\Scripts\activate

    # Linux/Mac
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install requests urllib3
    # Or if you have a requirements file:
    # pip install -r requirements.txt
    ```

## ⚙️ Configuration

### 1. Authentication
This script requires a valid VTEX authentication cookie (`VtexIdclientAutCookie`).

** SECURITY WARNING:** Never commit your actual cookie to GitHub. Use environment variables.


