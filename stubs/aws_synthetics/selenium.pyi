from selenium.webdriver.chrome.webdriver import WebDriver

class _SyntheticsWebDriver:
    def Chrome(self, *args: object, **kwargs: object) -> WebDriver: ...
    def take_screenshot(self, name: str, suffix: str = ...) -> None: ...

synthetics_webdriver: _SyntheticsWebDriver
