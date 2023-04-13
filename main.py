import json
import requests
from typing import Dict

from bs4 import BeautifulSoup


DOMAIN = 'www.babycharlotte.com'
N_PRODUCT_PAGES = 184


def find_eggs_on_collections_page(url: str) -> Dict[str, str]:
    print('Checking for eggs on', url)
    soup = BeautifulSoup(requests.get(url).text, 'html.parser')

    product_links = []

    for link_node in soup.find_all('a'):
        if 'collections/all/products' in link_node.get('href', ''):
            # this points to a product
            images = link_node.find_all('img')
            for image in images:
                if 'EGG_' in image['src']:
                    product_links.append(link_node['href'])

    # get title of each egg product
    products = {}
    for link in product_links:
        if link.startswith('/'):
            link = f'https://{DOMAIN}' + link

        soup = BeautifulSoup(requests.get(link).text, 'html.parser')
        # find title
        title = soup.find(class_="product_name").text
        # and add to found products
        products[title] = link

    return products


def main():
    eggs = {}
    for i in range(1, N_PRODUCT_PAGES + 1):
        url = f'https://{DOMAIN}/collections/all?page={i}'
        eggs.update(find_eggs_on_collections_page(url))

    print('Found', len(eggs), 'eggs!')
    print(json.dumps(eggs, indent=2))


if __name__ == '__main__':
    main()
