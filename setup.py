import io
import re
import sys

from setuptools import (
    find_packages,
    setup,
)

if sys.version_info < (3, 5):
    raise Exception('Quma requires Python 3.5 or higher.')

with io.open('quma/__init__.py', 'rt', encoding='utf8') as f:
    version = re.search(r'__version__ = \'(.*?)\'', f.read()).group(1)

with io.open('README.rst', 'rt', encoding='utf8') as f:
    README = f.read()

setup(
    name='quma',
    version=version,
    description='quma',
    long_description=README,
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Topic :: Database :: Front-Ends',
    ],
    author='ebene fünf GmbH',
    author_email='info@ebenefuenf.de',
    license='MIT License',
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    test_suite='quma.tests',
    install_requires=['psycopg2'],
    tests_require=['pytest'],
    extras_require={
        'templates': ['mako'],
    }
)
