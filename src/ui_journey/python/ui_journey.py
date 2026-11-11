import os

from aws_synthetics.selenium import synthetics_webdriver as syn_webdriver
from aws_synthetics.common import synthetics_logger as logger
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

PAGE_URL = os.environ["PAGE_URL"]
# TODO: replace with the real selectors once the UI exposes stable ids
APP_ROOT = os.environ.get("APP_ROOT_SELECTOR", "body")
WAIT_SECONDS = 20


def main():
    browser = syn_webdriver.Chrome()
    browser.get(PAGE_URL)
    syn_webdriver.take_screenshot("page_loaded", "succeeded")

    WebDriverWait(browser, WAIT_SECONDS).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, APP_ROOT))
    )
    logger.info("App root %s visible on %s", APP_ROOT, PAGE_URL)

    # TODO: type a query into the search box and assert results render.

    errors = [
        e for e in browser.get_log("browser")
        if e["level"] == "SEVERE" and "Failed to load resource" not in e["message"]
    ]
    if errors:
        raise Exception(f"Browser console errors: {errors}")


def handler(event, context):
    return main()
