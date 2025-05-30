from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
from typing import List, Tuple, Type, Dict
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from fake_useragent import UserAgent
from selenium_stealth import stealth
import undetected_chromedriver as uc
import chromedriver_autoinstaller
import time
import random
import os
import shutil
import markdownify
import sys
import re

from sources.utility import pretty_print, animate_thinking
from sources.logger import Logger

def get_chrome_path() -> str:
    """Get the path to the Chrome executable."""
    if sys.platform.startswith("win"):
        paths = [
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google\\Chrome\\Application\\chrome.exe")  # User install
        ]
    elif sys.platform.startswith("darwin"):  # macOS
        paths = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"]
    else:  # Linux
        paths = ["/usr/bin/google-chrome", "/usr/bin/chromium-browser", "/usr/bin/chromium"]

    for path in paths:
        if os.path.exists(path) and os.access(path, os.X_OK):  # Check if executable
            return path
    return None

def create_driver(headless=False, stealth_mode=True) -> webdriver.Chrome:
    """Create a Chrome WebDriver with specified options."""
    chrome_options = Options()
    chrome_path = get_chrome_path()
    
    if not chrome_path:
        raise FileNotFoundError("Google Chrome not found. Please install it.")
    chrome_options.binary_location = chrome_path
    
    if headless:
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-webgl")
    #ua = UserAgent()
    #user_agent = ua.random # NOTE sometime return wrong user agent, investigate
    #chrome_options.add_argument(f'user-agent={user_agent}')
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--autoplay-policy=user-gesture-required")
    chrome_options.add_argument("--mute-audio")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument('--window-size=1080,560')
    if not stealth_mode:
        # crx file can't be installed in stealth mode
        crx_path = "./crx/nopecha.crx"
        if not os.path.exists(crx_path):
            raise FileNotFoundError(f"Extension file not found at: {crx_path}")
        chrome_options.add_extension(crx_path)
    
    chromedriver_path = shutil.which("chromedriver")
    if not chromedriver_path:
        chromedriver_path = chromedriver_autoinstaller.install()
    
    if not chromedriver_path:
        raise FileNotFoundError("ChromeDriver not found. Please install it or add it to your PATH.")
    
    service = Service(chromedriver_path)
    if stealth_mode:
        driver = uc.Chrome(service=service, options=chrome_options)
        stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )
        return driver
    security_prefs = {
        "profile.default_content_setting_values.media_stream": 2,
        "profile.default_content_setting_values.geolocation": 2,
        "safebrowsing.enabled": True,
    }
    chrome_options.add_experimental_option("prefs", security_prefs)
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    return webdriver.Chrome(service=service, options=chrome_options)

class Browser:
    def __init__(self, driver, anticaptcha_manual_install=False):
        """Initialize the browser with optional AntiCaptcha installation."""
        self.js_scripts_folder = "./sources/web_scripts/" if not __name__ == "__main__" else "./web_scripts/"
        self.anticaptcha = "https://chrome.google.com/webstore/detail/nopecha-captcha-solver/dknlfmjaanfblgfdfebhijalfmhmjjjo/related"
        self.logger = Logger("browser.log")
        try:
            self.driver = driver
            self.wait = WebDriverWait(self.driver, 10)
        except Exception as e:
            raise Exception(f"Failed to initialize browser: {str(e)}")
        self.driver.get("https://www.google.com")
        if anticaptcha_manual_install:
            self.load_anticatpcha_manually()
            
    def load_anticatpcha_manually(self):
        pretty_print("You might want to install the AntiCaptcha extension for captchas.", color="warning")
        self.driver.get(self.anticaptcha)

    def go_to(self, url:str) -> bool:
        """Navigate to a specified URL."""
        try:
            initial_handles = self.driver.window_handles
            self.driver.get(url)
            wait = WebDriverWait(self.driver, timeout=30)
            wait.until(
                lambda driver: (
                    driver.execute_script("return document.readyState") == "complete" and
                    not any(keyword in driver.page_source.lower() for keyword in ["checking your browser", "verifying", "captcha"])
                ),
                message="stuck on 'checking browser' or verification screen"
            )
            self.apply_web_safety()
            self.logger.log(f"Navigated to: {url}")
            return True
        except TimeoutException as e:
            self.logger.error(f"Timeout waiting for {url} to load: {str(e)}")
            return False
        except WebDriverException as e:
            self.logger.error(f"Error navigating to {url}: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Fatal error with go_to method on {url}:\n{str(e)}")
            raise e

    def is_sentence(self, text:str) -> bool:
        """Check if the text qualifies as a meaningful sentence or contains important error codes."""
        text = text.strip()

        if any(c.isdigit() for c in text):
            return True
        words = re.findall(r'\w+', text, re.UNICODE)
        word_count = len(words)
        has_punctuation = any(text.endswith(p) for p in ['.', '，', ',', '!', '?', '。', '！', '？', '।', '۔'])
        is_long_enough = word_count > 4
        return (word_count >= 5 and (has_punctuation or is_long_enough))

    def get_text(self) -> str | None:
        """Get page text as formatted Markdown"""
        try:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            for element in soup(['script', 'style', 'noscript', 'meta', 'link']):
                element.decompose()
            markdown_converter = markdownify.MarkdownConverter(
                heading_style="ATX",
                strip=['a'],
                autolinks=False,
                bullets='•',
                strong_em_symbol='*',
                default_title=False,
            )
            markdown_text = markdown_converter.convert(str(soup.body))
            lines = []
            for line in markdown_text.splitlines():
                stripped = line.strip()
                if stripped and self.is_sentence(stripped):
                    cleaned = ' '.join(stripped.split())
                    lines.append(cleaned)
            result = "[Start of page]\n\n" + "\n\n".join(lines) + "\n\n[End of page]"
            result = re.sub(r'!\[(.*?)\]\(.*?\)', r'[IMAGE: \1]', result)
            return result[:8192]
        except Exception as e:
            self.logger.error(f"Error getting text: {str(e)}")
            return None
    
    def clean_url(self, url:str) -> str:
        """Clean URL to keep only the part needed for navigation to the page"""
        clean = url.split('#')[0]
        parts = clean.split('?', 1)
        base_url = parts[0]
        if len(parts) > 1:
            query = parts[1]
            essential_params = []
            for param in query.split('&'):
                if param.startswith('_skw=') or param.startswith('q=') or param.startswith('s='):
                    essential_params.append(param)
                elif param.startswith('_') or param.startswith('hash=') or param.startswith('itmmeta='):
                    break
            if essential_params:
                return f"{base_url}?{'&'.join(essential_params)}"
        return base_url
    
    def is_link_valid(self, url:str) -> bool:
        """Check if a URL is a valid link (page, not related to icon or metadata)."""
        if len(url) > 64:
            return False
        parsed_url = urlparse(url)
        if not parsed_url.scheme or not parsed_url.netloc:
            return False
        if re.search(r'/\d+$', parsed_url.path):
            return False
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']
        metadata_extensions = ['.ico', '.xml', '.json', '.rss', '.atom']
        for ext in image_extensions + metadata_extensions:
            if url.lower().endswith(ext):
                return False
        return True

    def get_navigable(self) -> List[str]:
        """Get all navigable links on the current page."""
        try:
            links = []
            elements = self.driver.find_elements(By.TAG_NAME, "a")
            
            for element in elements:
                href = element.get_attribute("href")
                if href and href.startswith(("http", "https")):
                    links.append({
                        "url": href,
                        "text": element.text.strip(),
                        "is_displayed": element.is_displayed()
                    })
            
            self.logger.info(f"Found {len(links)} navigable links")
            return [self.clean_url(link['url']) for link in links if (link['is_displayed'] == True and self.is_link_valid(link['url']))]
        except Exception as e:
            self.logger.error(f"Error getting navigable links: {str(e)}")
            return []

    def click_element(self, xpath: str) -> bool:
        """Click an element specified by XPath."""
        try:
            element = self.wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
            if not element.is_displayed():
                return False
            if not element.is_enabled():
                return False
            try:
                self.logger.error(f"Scrolling to element for click_element.")
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", element)
                time.sleep(0.1)
                element.click()
                return True
            except ElementClickInterceptedException as e:
                self.logger.error(f"Error click_element: {str(e)}")
                return False
        except TimeoutException:
            self.logger.warning(f"Timeout clicking element.")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error clicking element at {xpath}: {str(e)}")
            return False
        
    def load_js(self, file_name: str) -> str:
        """Load javascript from script folder to inject to page."""
        path = os.path.join(self.js_scripts_folder, file_name)
        self.logger.info(f"Loading js at {path}")
        try:
            with open(path, 'r') as f:
                return f.read()
        except FileNotFoundError as e:
            raise Exception(f"Could not find: {path}") from e
        except Exception as e:
            raise e

    def find_all_inputs(self, timeout=3):
        """Find all inputs elements on the page."""
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except Exception as e:
            self.logger.error(f"Error waiting for input element: {str(e)}")
            return []
        time.sleep(0.5)
        script = self.load_js("find_inputs.js")
        input_elements = self.driver.execute_script(script)
        return input_elements

    def get_form_inputs(self) -> List[str]:
        """Extract all input from the page and return them."""
        try:
            input_elements = self.find_all_inputs()
            if not input_elements:
                self.logger.info("No input element on page.")
                return ["No input forms found on the page."]

            form_strings = []
            for element in input_elements:
                input_type = element.get("type") or "text"
                if input_type in ["hidden", "submit", "button", "image"] or not element["displayed"]:
                    continue
                input_name = element.get("text") or element.get("id") or input_type
                if input_type == "checkbox" or input_type == "radio":
                    try:
                        checked_status = "checked" if element.is_selected() else "unchecked"
                    except Exception as e:
                        continue
                    form_strings.append(f"[{input_name}]({checked_status})")
                else:
                    form_strings.append(f"[{input_name}]("")")
            return form_strings

        except Exception as e:
            raise e

    def get_buttons_xpath(self) -> List[str]:
        """
        Find buttons and return their type and xpath.
        """
        buttons = self.driver.find_elements(By.TAG_NAME, "button") + \
                  self.driver.find_elements(By.XPATH, "//input[@type='submit']")
        result = []
        for i, button in enumerate(buttons):
            if not button.is_displayed() or not button.is_enabled():
                continue
            text = (button.text or button.get_attribute("value") or "").lower().replace(' ', '')
            xpath = f"(//button | //input[@type='submit'])[{i + 1}]"
            result.append((text, xpath))
        result.sort(key=lambda x: len(x[0]))
        return result

    def find_and_click_submission(self, timeout: int = 10) -> bool:
        possible_submissions = ["login", "submit", "register", "calculate", "login", "submit", "register", "calculate", "save", "send",
                                "continue", "apply", "ok", "confirm", "next", "proceed", "accept", "agree", "yes", "no", "cancel",
                                "close", "done", "finish", "start", "calculate"]
        for submission in possible_submissions:
            if self.find_and_click_btn(submission, timeout):
                return True
        self.logger.warning("No submission button found")
        return False

    def find_and_click_btn(self, btn_type: str = 'login', timeout: int = 10) -> bool:
        """Find and click a submit button matching the specified type."""
        buttons = self.get_buttons_xpath()
        if not buttons:
            self.logger.warning("No visible buttons found")
            return False

        for button_text, xpath in buttons:
            if btn_type.lower() in button_text.lower():
                try:
                    wait = WebDriverWait(self.driver, timeout)
                    element = wait.until(
                        EC.element_to_be_clickable((By.XPATH, xpath)),
                        message=f"Button with XPath '{xpath}' not clickable within {timeout} seconds"
                    )
                    if self.click_element(xpath):
                        return True
                    else:
                        return False
                except TimeoutException:
                    self.logger.warning(f"Timeout waiting for '{button_text}' button at XPath: {xpath}")
                    return False
                except Exception as e:
                    self.logger.error(f"Error clicking button '{button_text}' at XPath: {xpath} - {str(e)}")
                    return False
        self.logger.warning(f"No button matching '{btn_type}' found")
        return False
    
    def find_input_xpath_by_name(self, inputs, name: str) -> str | None:
        for field in inputs:
            if name in field["text"]:
                return field["xpath"]
        return None

    def fill_form_inputs(self, input_list: List[str]) -> bool:
        """Fill form inputs based on a list of [name](value) strings."""
        if not isinstance(input_list, list):
            self.logger.error("input_list must be a list")
            return False
        inputs = self.find_all_inputs()
        try:
            for input_str in input_list:
                match = re.match(r'\[(.*?)\]\((.*?)\)', input_str)
                if not match:
                    self.logger.warning(f"Invalid format for input: {input_str}")
                    continue

                name, value = match.groups()
                name = name.strip()
                value = value.strip()
                xpath = self.find_input_xpath_by_name(inputs, name)
                if not xpath:
                    continue
                element = self.driver.find_element(By.XPATH, xpath)
                input_type = (element.get_attribute("type") or "text").lower()
                if input_type in ["checkbox", "radio"]:
                    is_checked = element.is_selected()
                    should_be_checked = value.lower() == "checked"

                    if is_checked != should_be_checked:
                        element.click()
                        self.logger.info(f"Set {name} to {value}")
                else:
                    element.clear()
                    element.send_keys(value)
                    self.logger.info(f"Filled {name} with {value}")
            return True
        except Exception as e:
            self.logger.error(f"Error filling form inputs: {str(e)}")
            return False

    def get_current_url(self) -> str:
        """Get the current URL of the page."""
        return self.driver.current_url

    def get_page_title(self) -> str:
        """Get the title of the current page."""
        return self.driver.title

    def scroll_bottom(self) -> bool:
        """Scroll to the bottom of the page."""
        try:
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            time.sleep(1)
            return True
        except Exception as e:
            self.logger.error(f"Error scrolling: {str(e)}")
            return False

    def screenshot(self, filename:str) -> bool:
        """Take a screenshot of the current page."""
        try:
            self.driver.save_screenshot(filename)
            self.logger.info(f"Screenshot saved as {filename}")
            return True
        except Exception as e:
            self.logger.error(f"Error taking screenshot: {str(e)}")
            return False

    def apply_web_safety(self):
        """
        Apply security measures to block any website malicious/annoying execution, privacy violation etc..
        """
        script = self.load_js("inject_safety_script.js")
        input_elements = self.driver.execute_script(script)

if __name__ == "__main__":
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    driver = create_driver()
    browser = Browser(driver, anticaptcha_manual_install=True)
    
    #browser.go_to("https://github.com/Fosowl/agenticSeek")
    #txt = browser.get_text()
    #print(txt)
    #browser.go_to("https://practicetestautomation.com/practice-test-login/")
    time.sleep(10)
    print("AntiCaptcha / Form Test")
    browser.go_to("https://www.google.com/recaptcha/api2/demo")
    inputs = browser.get_form_inputs()
    #inputs = ['[input1](Martin)', f'[input2](Test)', '[input3](test@gmail.com)']
    browser.fill_form_inputs(inputs)
    browser.find_and_click_submission()
    time.sleep(10)
