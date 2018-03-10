from __future__ import unicode_literals

import setuptools

setuptools.setup(
    name='flake8-aaa',

    # --- META ---
    description='Flake8 plugin to check the style of Python tests to 3A standard',
    license='MIT',
    version='0.0.0',

    # --- Python ---
    packages=['flake8_aaa'],
    py_modules=['flake8_aaa'],
    install_requires=[
        'flake8 > 3',
        'py > 1.5',
    ],
    entry_points={
        'flake8.extension': [
            'AAA = flake8_aaa:Checker',
        ],
    },
)
