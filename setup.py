import setuptools

setuptools.setup(
    name="named1",
    version="0.0.5",
    author="L. Kärkkäinen",
    author_email="tronic@noreply.users.github.com",
    description="DNS server with DNS-over-HTTPS and Redis caching",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/Tronic/named1",
    packages=setuptools.find_packages(),
    classifiers = [
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires = [
        "trio>=0.12",
        "trio-redis",
        "h2",
        "dnspython",
    ],
    dependency_links = [
        "https://github.com/Tronic/trio-redis/tarball/master#egg=trio-redis",
    ],
    include_package_data = True,
)
