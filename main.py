# vim: tabstop=4 shiftwidth=4 expandtab
from __future__ import annotations

import asyncio
import html.parser
import json
import pathlib
import random
import re
import time
import urllib.parse
from collections import defaultdict
from typing import Callable, Iterable

import httpx  # https://github.com/encode/httpx

#BASE_SLEEP_DURATION_SECONDS = 1
BASE_SLEEP_DURATION_SECONDS = 3
# starting at 0, how deep should we traverse?
MAX_DEPTH = 1

# example:
# https://cdn.shopify.com/s/files/1/0450/5013/4679/products/EGG_2weangreencarrot7oz_600x.png?v=1680797763
# re.findall(regex, string): List

EGG_REGEX = r'cdn.shopify.com\S+EGG\S+\.png'

class UrlFilterer:
    def __init__(
            self,
            allowed_domains: set[str] | None = None,
            allowed_schemes: set[str] | None = None,
            allowed_filetypes: set[str] | None = None,
    ):
        self.allowed_domains = allowed_domains
        self.allowed_schemes = allowed_schemes
        self.allowed_filetypes = allowed_filetypes

    def filter_url(self, base: str, url: str) -> str | None:
        if url.startswith('https://www.babycharlotte.com'):
            pass
        else:
            # assuming url is a path, something else '/collections/jellycat'
            url = urllib.parse.urljoin(base, url)
            url, _frag = urllib.parse.urldefrag(url)
        #import pdb; pdb.set_trace()

        parsed = urllib.parse.urlparse(url)
        if (self.allowed_schemes is not None
                and parsed.scheme not in self.allowed_schemes):
            return None
        if (self.allowed_domains is not None
                and parsed.netloc not in self.allowed_domains):
            return None
        ext = pathlib.Path(parsed.path).suffix
        if (self.allowed_filetypes is not None
                and ext not in self.allowed_filetypes):
            return None
        return url


class UrlParser(html.parser.HTMLParser):
    def __init__(
            self,
            base: str,
            filter_url: Callable[[str, str], str | None]
    ):
        super().__init__()
        self.base = base
        self.filter_url = filter_url
        self.found_links = set()

    def handle_starttag(self, tag: str, attrs):
        # look for <a href="...">
        if tag != "a":
            return

        for attr, url in attrs:
            if attr != "href":
                continue

            if (url := self.filter_url(self.base, url)) is not None:
                self.found_links.add(url)


class Crawler:
    def __init__(
            self,
            client: httpx.AsyncClient,
            urls: Iterable[str],
            filter_url: Callable[[str, str], str | None],
            workers: int = 10,
            limit: int = 25,
    ):
        self.client = client

        self.start_urls = set(urls)
        self.todo = asyncio.Queue()
        self.seen = set()
        self.done = set()

        self.filter_url = filter_url
        self.num_workers = workers
        self.limit = limit
        self.total = 0

        # store parent to eggs
        self.eggs = defaultdict(list)

    async def run(self):
        start_depth = 0

        await self.on_found_links(self.start_urls, start_depth)  # prime the queue
        workers = [
            asyncio.create_task(self.worker())
            for _ in range(self.num_workers)
        ]
        await self.todo.join()

        for worker in workers:
            worker.cancel()

    async def worker(self):
        while True:
            try:
                await self.process_one()
            except asyncio.CancelledError:
                return

    async def process_one(self):
        url, depth = await self.todo.get()
        try:
            await self.crawl(url, depth)
        except Exception as exc:
            # retry handling here...
            print('encountered exception:', exc)
        finally:
            self.todo.task_done()

    def find_eggs(self, text: str) -> list:
        # find images, search for eggs and add to list
        return re.findall(EGG_REGEX, text)

    async def crawl(self, url: str, depth: int):
        print('crawlingg', url)

        # rate limit here...
        # sleep between 0.5 and 1.5 seconds
        sleep_dur = BASE_SLEEP_DURATION_SECONDS + random.random() - 0.5
        await asyncio.sleep(sleep_dur)

        response = await self.client.get(url, follow_redirects=True)

        # get images
        eggs = self.find_eggs(response.text)
        if eggs:
            self.eggs[url].extend(eggs)

        found_links = await self.parse_links(
            base=str(response.url),
            text=response.text,
        )

        await self.on_found_links(found_links, depth)

        self.done.add(url)

    async def parse_links(self, base: str, text: str) -> set[str]:
        parser = UrlParser(base, self.filter_url)
        parser.feed(text)
        return parser.found_links

    async def on_found_links(self, urls: set[str], depth: int):
        new = urls - self.seen
        self.seen.update(new)

        # await save to database or file here...

        for url in new:
            await self.put_todo(url, depth)

    async def put_todo(self, url: str, depth: int):
        if depth == MAX_DEPTH:
            # don't go any deeper
            return

        if self.total >= self.limit:
            return
        self.total += 1
        await self.todo.put((url, depth + 1))


async def main():
    filterer = UrlFilterer(
        #allowed_domains={"babycharlotte"},
        allowed_domains={"babycharlotte.com", "www.babycharlotte.com"},
        allowed_schemes={"http", "https"},
        allowed_filetypes={".html", ".php", ""},
    )

    start = time.perf_counter()
    async with httpx.AsyncClient() as client:
        crawler = Crawler(
            client=client,
            urls=("https://www.babycharlotte.com/collections/all?page=" + str(i)
                  for i in range(185)),
            filter_url=filterer.filter_url,
            workers=5,
            limit=10000,
        )
        await crawler.run()
    end = time.perf_counter()

    seen = sorted(crawler.seen)
    print("Results:")
    for url in seen:
        print(url)
    print(f"Crawled: {len(crawler.done)} URLs")
    print(f"Found: {len(seen)} URLs")
    print(f"Done in {end - start:.2f}s")

    print()
    print()
    print("Eggs found:")
    print(json.dumps(crawler.eggs, indent=2))


if __name__ == '__main__':
    print('running crawler')
    asyncio.run(main(), debug=True)
