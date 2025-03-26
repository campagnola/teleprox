from setuptools import setup, find_packages

packages = [x for x in find_packages('.') if x.startswith('teleprox')]

setup(
    name = "teleprox",
    version = "1.1",
    author = "Luke Campagnola, Martin Chase, Samuel Garcia",
    description = ("Object proxies over TCP"),
    license = "BSD",
    url = "http://github.com/campagnola/teleprox",
    packages=packages,
    classifiers=[],
)


