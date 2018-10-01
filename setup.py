import platform
import re
import sys

from setuptools import (
    find_packages,
    setup,
)

if sys.version_info < (3, 5):
    raise Exception('quma requires Python 3.5 or higher.')


with open('quma/__init__.py', 'rt', encoding='utf8') as f:
    version = re.search(r'__version__ = \'(.*?)\'', f.read()).group(1)

with open('README.rst', 'rt', encoding='utf8') as f:
    README = f.read()

test = ['pytest', 'pytest-cov']
impl = platform.python_implementation()
extras = {
    'test':  test,
    'templates': ['mako'],
    'postgres': ['psycopg2'],
    'mysql': ['mysqlclient'],
}
if impl == 'PyPy':
    extras['postgres'] = 'psycopg2cffi'

setup(
    name='quma',
    version=version,
    description='quma',
    long_description=README,
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: Database :: Front-Ends',
    ],
    author='ebene fünf GmbH',
    author_email='info@ebenefuenf.de',
    license='MIT License',
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    test_suite='quma.tests',
    setup_requires=['pytest-runner'],
    tests_require=test,
    extras_require=extras
)
