import setuptools

setuptools.setup(
    name="named1",
    version="0.0.1",
    author="L. Kärkkäinen",
    author_email="tronic@noreply.users.github.com",
    description="DNS server with DNS-over-HTTPS and Redis caching",
    long_description="A caching DNS server that uses Google and Cloudflare DNS-over-HTTPS and answers queries on UDP port 53 super-fast.",
    long_description_content_type="text/markdown",
    url="https://github.com/Tronic/named1",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)