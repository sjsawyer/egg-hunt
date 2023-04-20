"""
Script for automating the annual Easter Egg hunt.
"""
import asyncio
import json
import logging
import os
import random
from typing import Dict

import aiohttp
import backoff
from bs4 import BeautifulSoup

# should resemble www.myfavoritedomain.com
DOMAIN = os.environ['DOMAIN']
KEYWORD = 'EGG_'
MAX_CONCURRENCY = 10
MAX_SLEEP_DURATION_SECONDS = 3

log = logging.getLogger(name='app')


@backoff.on_exception(
    backoff.expo, aiohttp.ClientError,
    max_tries=3, max_time=5)
async def fetch_url(
        url: str,
        semaphore: asyncio.Semaphore,
        client: aiohttp.ClientSession) -> str:
    """Fetch the raw html content of a single url."""
    async with semaphore:
        await asyncio.sleep(random.random() * MAX_SLEEP_DURATION_SECONDS)
        log.debug('fetching url %s', url)
        resp = await client.get(url, raise_for_status=True)
    return await resp.text()


async def fetch_product_title(
        url: str,
        semaphore: asyncio.Semaphore,
        client: aiohttp.ClientSession) -> str:
    """Given the product url, get the title."""
    text = await fetch_url(url, semaphore, client)
    soup = BeautifulSoup(text, 'html.parser')

    return soup.find(class_='product_name').text


async def find_eggs_on_collections_page(
        url: str,
        semaphore: asyncio.Semaphore,
        client: aiohttp.ClientSession) -> Dict[str, str]:
    """Given a product collections page, find all the eggs."""
    text = await fetch_url(url, semaphore, client)
    soup = BeautifulSoup(text, 'html.parser')

    product_links = []
    for link_node in soup.find_all('a'):
        # Make sure this points to a product.
        if 'collections/all/products' not in link_node.get('href', ''):
            continue

        # Check if this image has an egg.
        images = link_node.find_all('img')
        if not any((KEYWORD in image['src'] for image in images)):
            continue

        # We have an egg, update the link if necessary and add it.
        link = link_node['href']
        if link.startswith('/'):
            link = f'https://{DOMAIN}' + link
        product_links.append(link)

    tasks = (fetch_product_title(url, semaphore, client)
             for url in product_links)
    titles = await asyncio.gather(*tasks)
    return dict(zip(product_links, titles))


async def get_num_product_pages(
        semaphore: asyncio.Semaphore,
        client: aiohttp.ClientSession) -> int:
    """Get largest page from the bottom navigation bar."""
    text = await fetch_url(
        f'https://{DOMAIN}/collections/all', semaphore, client)
    soup = BeautifulSoup(text, 'html.parser')
    return max(
        int(node.text) for node in
        soup.find(
            'div', class_='paginate'
        ).find_all(class_='page')
    )


async def main() -> None:
    """Fetch eggs from all pages asynchronously."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    async with aiohttp.ClientSession() as session:
        n_pages = await get_num_product_pages(semaphore, session)
        log.debug('Detected %d product pages', n_pages)

        urls = (f'https://{DOMAIN}/collections/all?page={i}'
                for i in range(1, n_pages + 1))
        tasks = (find_eggs_on_collections_page(url, semaphore, session)
                 for url in urls)
        eggs_from_each_page = await asyncio.gather(*tasks)

        all_eggs = {}
        for eggs_from_one_page in eggs_from_each_page:
            all_eggs.update(eggs_from_one_page)

    log.info('Found %d eggs!', len(all_eggs))
    log.info('Eggs:\n%s', json.dumps(all_eggs, indent=2))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
