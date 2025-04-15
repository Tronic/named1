# Named1 DNS server

A very experimental DNS server with local RAM caching.

Cloudflare and Google public DNS servers are used by DNS-over-HTTPS so that the
requests are secure and pass through any firewalls as well as public WIFI login
page redirects.

This server maintains two connections to each provider, so that queries can be
answered quickly. An incoming query is looked up in each provider and whichever
responds fastest gets reported back. The fastest answer as well as any other
answers that arrive get cached (if Redis database is installed) so that the
next time upstream DNS don't even need to be queried.

"Happy eyeballs" style fallback is used within each provider, so that if one of the
servers doesn't respond quickly enough, the other one gets queried as well.
Again, the fastest response wins.

The server listens for incoming requests on UDP port 53, so that it can be
reached by local systems without need to setup DNS-over-HTTPS.

Cached answers take about 1 ms. Typical remote lookups on fast networks are in
30 ms ballpark. Due to asynchronous implementation over HTTP/2 streams, a large
number of requests can be done concurrently without slowing down the others.

## Run directly with UV

```shell
uvx --from git+https://github.com/Tronic/named1.git named1
```

Note: You may need to be root to listen on port 53 (DNS).

## Installation

```python
uv venv
source .venv/bin/activate
uv pip install git+https://github.com/Tronic/named1.git
sudo named1
```

## Configuration

Use `named1 -d` to enable debug mode, that displays the queries and statistics on which provider was the fastest to respond.

This will by default listen on IPv4 and IPv6 port 53 for
connections from anywhere. Redis is connected without password (keys of form
dns:hostname.tld. are created). Google and Cloudflare are hardcoded. Edit the
source code as needed.

Earlier versions used Redis for caching, but since v0.2.0 RAM caching is done directly in Python. Cache is lost on named1 restarts.

## Test requests

By using ````dig +nsid```` you will get a NSID response stating where the answer
came from:

```
$ dig slashdot.org +nsid -t ANY

; <<>> DiG 9.10.6 <<>> slashdot.org +nsid -t ANY
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 54185
;; flags: qr rd ra; QUERY: 1, ANSWER: 13, AUTHORITY: 0, ADDITIONAL: 1

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 8192
; NSID: 6e 61 6d 65 64 31 2f 67 6f 6f 67 6c 65 3a 20 52 65 73 70 6f 6e 73 65 20 66 72 6f 6d 20 32 30 38 2e 38 30 2e 31 32 37 2e 32 2e ("named1/google: Response from 208.80.127.2.")
;; QUESTION SECTION:
;slashdot.org.			IN	ANY

;; ANSWER SECTION:
slashdot.org.		899	IN	A	216.105.38.15
slashdot.org.		21599	IN	SOA	ns0.dnsmadeeasy.com. hostmaster.slashdotmedia.com. 2016210769 14400 600 604800 300
slashdot.org.		21599	IN	NS	ns3.dnsmadeeasy.com.
slashdot.org.		21599	IN	NS	ns2.dnsmadeeasy.com.
slashdot.org.		21599	IN	NS	ns1.dnsmadeeasy.com.
slashdot.org.		21599	IN	NS	ns0.dnsmadeeasy.com.
slashdot.org.		21599	IN	NS	ns4.dnsmadeeasy.com.
slashdot.org.		3599	IN	MX	10 mx.sourceforge.net.
slashdot.org.		3599	IN	TXT	"brave-ledger-verification=4d77fce14921bcdfa7fb16e9086b7006958551a1fddd0bad8181c14cc63fa9e5"
slashdot.org.		3599	IN	TXT	"google-site-verification=mwj5KfwLNG8eetH4m5w1VEUAzUlHotrNwnprxNQN5Io"
slashdot.org.		3599	IN	TXT	"v=spf1 include:servers.mcsv.net ip4:216.105.38.0/26 ip4:216.34.181.51 ?all"
slashdot.org.		3599	IN	TXT	"google-site-verification=ZbCscTBXGpjHX5RXLk1jcBu2tufiv-2mOmk_YZ4HWag"
slashdot.org.		3599	IN	TXT	"google-site-verification=uNYSi1PcKvBrZjpA8ftcmExM2qpIK5OMd6I13B2m8YI"

;; Query time: 130 msec
;; SERVER: 127.0.0.1#53(127.0.0.1)
;; WHEN: Sat Aug 10 16:03:04 EEST 2019
;; MSG SIZE  rcvd: 736

$ dig slashdot.org +nsid -t TXT

; <<>> DiG 9.10.6 <<>> slashdot.org +nsid -t TXT
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 37894
;; flags: qr rd ra; QUERY: 1, ANSWER: 5, AUTHORITY: 0, ADDITIONAL: 1

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 8192
; NSID: 6e 61 6d 65 64 31 2f 52 65 64 69 73 43 61 63 68 65 ("named1/RedisCache")
;; QUESTION SECTION:
;slashdot.org.			IN	TXT

;; ANSWER SECTION:
slashdot.org.		3574	IN	TXT	"brave-ledger-verification=4d77fce14921bcdfa7fb16e9086b7006958551a1fddd0bad8181c14cc63fa9e5"
slashdot.org.		3574	IN	TXT	"google-site-verification=mwj5KfwLNG8eetH4m5w1VEUAzUlHotrNwnprxNQN5Io"
slashdot.org.		3574	IN	TXT	"v=spf1 include:servers.mcsv.net ip4:216.105.38.0/26 ip4:216.34.181.51 ?all"
slashdot.org.		3574	IN	TXT	"google-site-verification=ZbCscTBXGpjHX5RXLk1jcBu2tufiv-2mOmk_YZ4HWag"
slashdot.org.		3574	IN	TXT	"google-site-verification=uNYSi1PcKvBrZjpA8ftcmExM2qpIK5OMd6I13B2m8YI"

;; Query time: 2 msec
;; SERVER: 127.0.0.1#53(127.0.0.1)
;; WHEN: Sat Aug 10 16:03:29 EEST 2019
;; MSG SIZE  rcvd: 495
```

Notice how Named1 cached the answers of the ANY query and was able to answer
the second query from RedisCache.

## Development

This program is based on Python ````trio```` async I/O framework. If you plan to
do any asynchronous programming on Python, do yourself a favour and stay far
away from the standard library ````asyncio```` module -- I found it to be not
only badly designed but also full of bugs.

Hyper ````h2```` is used for HTTP/2 and ````dnspython```` for wire-format DNS
messages.
