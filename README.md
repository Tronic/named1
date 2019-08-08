# Named1 DNS server

A very experimental DNS server with Redis caching.

Cloudflare and Google public DNS servers are used by DNS-over-HTTPS so that the
requests are secure and pass through any firewalls as well as public WIFI login
page redirects.

This server maintains two connections to each provider, so that queries can be
answered quickly. An incoming query is looked up in each provider and whichever
responds fastest gets reported back. The fastest answer as well as any other
answers that arrive get cached (if Redis database is installed) so that the
next time upstream DNS don't even need to be queried.

"Happy eyes" style fallback is used within each provider, so that if one of the
servers doesn't respond quickly enough, the other one gets queried as well.
Again, the fastest response wins.

The server listens for incoming requests on UDP port 53, so that it can be
reached by local systems without need to setup DNS-over-HTTPS.

Cached answers take about 1 ms. Typical remote lookups on fast networks are in
30 ms ballpark. Due to asynchronous implementation over HTTP/2 streams, a large
number of requests can be done concurrently without slowing down the others.

## Installation

Linux:

````
pip3 install git+https://github.com/Tronic/named1.git
sudo apt install redis
sudo python3 -m named1
````

MacOS:

````
pip3 install git+https://github.com/Tronic/named1.git
brew install redis
python3 -m named1
````

Redis is optional. If it is not installed, Named1 works as a non-caching DNS
server. Even then it should considerably speed up your name lookups.

## Configuration

Not implemented. This will by default listen on IPv4 and IPv6 port 53 for
connections from anywhere. Redis is connected without password (keys of form
dns:hostname.tld. are created). Google and Cloudflare are hardcoded. Edit the
source code as needed.

## Development

For more detailed output (incl. any successful lookups and which provider was
fastest), use Python developer mode:

````
python3 -X dev -m named1
````

This program is based on Python ````trio```` async I/O framework. If you plan to
do any asynchronous programming on Python, do yourself a favour and stay far
away from the standard library ````asyncio```` module -- I found it to be not
only badly designed but also full of bugs.

Hyper ````h2```` is used for HTTP/2 and ````dnspython``` for wire-format DNS
messages.