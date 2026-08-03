#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pyamlboot — Amlogic USB Boot Protocol Library
setup.py for pip installation
"""
from setuptools import setup, find_packages

setup(
    name="pyamlboot",
    version="1.0.0",
    description="Amlogic USB Boot Protocol Library — GXL/AXG/G12 compatible",
    long_description=(
        "Python library implementing the Amlogic USB Boot Protocol. "
        "Allows loading BL2/DDR and U-Boot into Amlogic SoCs via USB, "
        "and flashing eMMC partitions. Based on superna9999/pyamlboot."
    ),
    author="aml-burn-tool",
    license="Apache-2.0 OR MIT",
    packages=find_packages(),
    install_requires=[
        "pyusb>=1.2.0",
    ],
    python_requires=">=3.6",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Topic :: System :: Hardware",
        "Topic :: Software Development :: Embedded Systems",
    ],
    entry_points={
        "console_scripts": [
            "aml-boot=pyamlboot.burn:main",
        ],
    },
)
