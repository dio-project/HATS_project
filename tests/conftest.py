"""Shared test configuration; isolate API tests from the local development database."""
import os

os.environ["HATS_DATABASE_URL"] = "sqlite://"
