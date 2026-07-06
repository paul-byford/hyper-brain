from __future__ import annotations

import pathlib

import pytest

from brain_app.embeddings.fake import FakeEmbeddings
from brain_app.indexer.build import build_index

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "corpus"

FINSERV = "finserv-ai-engineering"
RECRUITMENT = "enterprise-ai-recruitment"
# The shared space granted to every signed-in caller via the wildcard grant.
COMMONS = "commons"


@pytest.fixture(scope="session")
def embeddings() -> FakeEmbeddings:
    return FakeEmbeddings()


@pytest.fixture(scope="session")
def index(embeddings: FakeEmbeddings):
    return build_index(CORPUS, embeddings=embeddings, provider_name="fake")
