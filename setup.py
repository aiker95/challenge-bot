from setuptools import setup, find_packages

setup(
    name="challenge-bot",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        "aiogram",
        "sqlalchemy",
        "alembic",
        "python-dotenv",
        "psycopg2-binary",
        "aiohttp",
    ],
) 