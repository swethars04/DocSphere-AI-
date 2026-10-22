import os
import uuid
import logging
import requests
import time
from config import Config

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)

def download_report_for_company(company_name, year=2026):
    """
    Launches Chrome in VISUAL (GUI) mode using Selenium, navigates to the NSE BRSR filings portal,
    types the company name, handles the autocomplete list selection, clicks 'GO',
    and downloads the official XBRL (XML) sustainability report.
    
    No mock data is generated. If not found, raises an exception.
    """
    logger.info(f"Triggering Selenium visual GUI scraping for: {company_name} (Year: {year})")
    
    # Destination file path
    dest_filename = f"scraped_{uuid.uuid4()}_{year}.xml"
    dest_path = os.path.join(Config.UPLOAD_FOLDER, dest_filename)
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    
    # Initialize Chrome options for visual execution
    options = webdriver.ChromeOptions()
    options.add_argument('--start-maximized')
    options.add_argument('--disable-gpu')
    
    # Bypassing exchange bot-defense
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = None
    try:
        # Initialize Chrome Driver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        # Override the navigator.webdriver property to bypass simple bot checks
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
        
        # Navigate to the exact NSE BRSR page (with spelling correction)
        nse_url = "https://www.nseindia.com/companies-listing/corporate-filings-bussiness-sustainabilitiy-reports"
        logger.info(f"Navigating visual Chrome to: {nse_url}")
        driver.get(nse_url)
        
        # Wait for placeholder 'Company Name' input to load
        wait = WebDriverWait(driver, 20)
        logger.info("Locating 'Company Name' input field...")
        
        search_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Company Name']")))
        
        # Type the company name character-by-character for human-like typing simulation
        logger.info(f"Typing query: {company_name}")
        search_input.click()
        search_input.clear()
        for char in company_name:
            search_input.send_keys(char)
            time.sleep(0.1)
            
        # Wait for the typeahead autocomplete suggestion to pop up
        logger.info("Waiting for autocomplete suggestion lists...")
        try:
            suggestion = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".tt-suggestion, .tt-selectable"))
            )
        except Exception:
            logger.warning(f"No suggestions found for company: {company_name}")
            raise Exception(f"The company '{company_name}' is not listed on the NSE Exchange, or does not have a public BRSR filing. Please check the spelling and try again.")
            
        logger.info(f"Found suggestion: '{suggestion.text}'. Clicking suggestion...")
        
        # Attempt native click first to fire typeahead.js JS events; fallback to JS click if blocked
        try:
            suggestion.click()
            logger.info("Clicked suggestion natively.")
        except Exception:
            driver.execute_script("arguments[0].click();", suggestion)
            logger.info("Clicked suggestion via JS.")
            
        time.sleep(1.5) # Allow dropdown close transition
        
        # Click the GO button
        logger.info("Clicking search 'GO' button...")
        go_btn = wait.until(EC.presence_of_element_located((By.XPATH, "//*[text()='GO'] | //button[contains(text(), 'GO')] | //input[@value='GO']")))
        
        try:
            go_btn.click()
            logger.info("Clicked GO button natively.")
        except Exception:
            driver.execute_script("arguments[0].click();", go_btn)
            logger.info("Clicked GO button via JS.")
        
        # Wait for table rows to load containing the search results
        logger.info("Waiting for results table to populate...")
        time.sleep(4.0)
        
        # Check if the results table contains a row
        xbrl_link_elem = wait.until(
            EC.presence_of_element_located((By.XPATH, "//td[@headers='xbrlFile']/a"))
        )
        
        # Extract the download link from the anchor element
        download_url = xbrl_link_elem.get_attribute("href")
        logger.info(f"XBRL filing URL located: {download_url}")
        
        # Highlight and click the element visually in Chrome so the user can watch the interaction
        driver.execute_script("arguments[0].scrollIntoView(true);", xbrl_link_elem)
        time.sleep(1.0)
        
        try:
            xbrl_link_elem.click()
            logger.info("Clicked XBRL link natively.")
        except Exception:
            driver.execute_script("arguments[0].click();", xbrl_link_elem)
            logger.info("Clicked XBRL link via JS.")
            
        time.sleep(3.0) # Hold window open for 3 seconds so the download trigger is clearly visible
        
        # Download the file programmatically using requests
        logger.info(f"Downloading filing dataset programmatically from link...")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': nse_url
        }
        res = requests.get(download_url, headers=headers, timeout=20)
        if res.status_code == 200:
            with open(dest_path, 'wb') as f:
                f.write(res.content)
            logger.info(f"Filing downloaded successfully and saved to: {dest_path}")
            return dest_path
        else:
            raise Exception(f"Failed to download filing from NSE link. Status code: {res.status_code}")
            
    except Exception as e:
        logger.error(f"Error executing visual search/scraping: {e}")
        # Capture error diagnostics screenshot
        if driver:
            error_screenshot = os.path.join(Config.UPLOAD_FOLDER, "scraper_error.png")
            driver.save_screenshot(error_screenshot)
            logger.error(f"Saved diagnostic screenshot of Chrome error to: {error_screenshot}")
            logger.error(f"Page URL at error: {driver.current_url}")
            logger.error(f"HTML snippet: {driver.page_source[:1000]}")
        raise Exception(f"Filing not found or blocked by exchange. Details: {str(e)}")
        
    finally:
        if driver:
            logger.info("Closing Selenium Chrome browser...")
            driver.quit()
