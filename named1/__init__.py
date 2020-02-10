import sys

__version__ = "0.1.0"

providers = {
    "cloudflare": {
        'host': 'cloudflare-dns.com',
        'path': '/dns-query',
        'ipv4': ('1.0.0.1', '1.1.1.1'),
        'ipv6': ('2606:4700:4700::1111', '2606:4700:4700::1001'),
    },
    "google": {
        'host': 'dns.google',
        'path': '/resolve',
        'ipv4': ["8.8.4.4", "8.8.8.8"],
        'ipv6': ['2001:4860:4860::8844', '2001:4860:4860::8888'],
    },
}

debug = sys.flags.debug
