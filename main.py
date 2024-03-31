import math
import multiprocessing
import re
from contextlib import asynccontextmanager
from typing import List

import uvicorn
from fastapi import FastAPI
from parsel import Selector

from adapter import RequestCrawler, PyppeteerCrawler, PlaywrightCrawler
from logger import logger
from models import CrawlerRequest, CrawlerResult


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    for crawler in ENABLE_CRAWLER:
        await crawler.close()


app = FastAPI(lifespan=lifespan,
              openapi_prefix="",
              openapi_url=None,
              docs_url=None,
              redoc_url=None)

core_count = multiprocessing.cpu_count()

playwright_count = math.floor(core_count * 0.8)

logger.info(f"Lazy loading : playwright:{playwright_count} pyppeteer:{core_count - playwright_count}")

request_crawler = RequestCrawler(timeout=5)
playwright_crawler = PlaywrightCrawler(browser_count=playwright_count)
pyppeteer_crawler = PyppeteerCrawler(browser_count=core_count - playwright_count)

ENABLE_CRAWLER = [
    request_crawler,
    pyppeteer_crawler,
    playwright_crawler
]

verify_keyword_list = ["验证", "verify", "robot", "captcha"]

verify_regex = re.compile('/authenticate/|/security/|/captcha/|/verify/', flags=re.IGNORECASE)

chinese_and_word_regex = re.compile('[\u4e00-\u9fa5]|[a-z-]+', flags=re.IGNORECASE)


def is_verification_page(title: str, html: str) -> bool:
    for verify in verify_keyword_list:
        if verify in title:
            return True
    selector: Selector = Selector(html)
    form_action_or_captcha_image_list: List[str] = selector.xpath('.//form/@action | .//img/@src').getall()
    for form_action_or_captcha_image in form_action_or_captcha_image_list:
        if verify_regex.findall(form_action_or_captcha_image):
            return True

    context = " ".join(selector.xpath('.//body//text()').getall())
    if len(chinese_and_word_regex.findall(context)) < 100:
        return True
    return False


@app.post("/extract")
async def extract(item: CrawlerRequest) -> CrawlerResult:
    logger.info(f"Received new request : {item.model_dump()}")

    request_result = await request_crawler.crawl(item)

    if request_result.success and not is_verification_page(title=request_result.title, html=request_result.html):
        return request_result

    if item.xhr:
        return await pyppeteer_crawler.crawl(item)
    else:
        return await playwright_crawler.crawl(item)


if __name__ == '__main__':
    uvicorn.run(app='main:app', host="0.0.0.0", port=8000)
