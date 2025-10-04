import os
from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="django-paystack-wallet",
    version="0.1.0",
    author="Ifeanyi Stanley Nnamani",
    author_email="nnamaniifeanyi10@gmail.com",
    description="A sophisticated Django wallet system integrated with Paystack",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/NzeStan/django-paystack-wallet",
    project_urls={
        "Bug Tracker": "https://github.com/NzeStan/django-paystack-wallet/issues",
        "Documentation": "https://django-paystack-wallet.readthedocs.io/",
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Framework :: Django",
        "Framework :: Django :: 3.2",
        "Framework :: Django :: 4.0",
        "Framework :: Django :: 4.1",
        "Framework :: Django :: 4.2",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    packages=find_packages(),
    include_package_data=True,
    python_requires=">=3.8",
    install_requires=[
        "Django>=3.2",
        "djangorestframework>=3.12.0",
        "requests>=2.25.0",
        "python-dateutil>=2.8.0",
        "pycryptodome>=3.10.0",
        "django-filter>=21.1",
        "django-model-utils>=4.2.0",
        "django-money>=3.0.0",
        "pytz>=2021.1",
        "celery>=5.2.0",
        "xlsxwriter>=3.0.0",
        "reportlab>=3.6.0",
    ],
    zip_safe=False,
)