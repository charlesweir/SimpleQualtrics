import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="SimpleQualtrics", # Replace with your own username
    version="1.0.2",
    author="Charles Weir",
    author_email="pypi.cafaw@xoxy.net",
    description="Python module to support Qualtrics APIs",
    keywords='qualtrics API https',
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/charlesweir/SimpleQualtrics",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
        "Natural Language :: English",
        "Topic :: Communications",
    ],
    python_requires='>=3.7',
    install_requires=[
       'requests>=2.25.1',
       'PyYAML>=5.3.1',
    ]
)
