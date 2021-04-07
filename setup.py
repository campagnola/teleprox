from setuptools import setup, find_packages

packages = [x for x in find_packages('.') if x.startswith('teleprox')]

setup(
    name = "teleprox",
    version = "1.0",
    author = "Luke Campagnola and Samuel Garcia",
    author_email = "lukec@alleninstitute.org",
    description = ("Object proxies over TCP"),
    license = "BSD",
    url = "http://github.com/campagnola/teleprox",
    packages=packages,
    classifiers=[],
)


