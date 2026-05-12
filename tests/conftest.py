"""Shared test fixtures for graphify-sf."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SIMPLE_PROJECT = FIXTURES_DIR / "simple_project"


@pytest.fixture
def simple_project_path():
    return SIMPLE_PROJECT


@pytest.fixture
def simple_detect_result(simple_project_path):
    from graphify_sf.detect import detect

    return detect(simple_project_path)


@pytest.fixture
def simple_extraction(simple_detect_result):
    from graphify_sf.extract import extract

    return extract(simple_detect_result, parallel=False)


@pytest.fixture
def simple_graph(simple_extraction):
    from graphify_sf.build import build_from_json, deduplicate_by_label

    nodes, edges = deduplicate_by_label(simple_extraction["nodes"], simple_extraction["edges"])
    return build_from_json({"nodes": nodes, "edges": edges})


@pytest.fixture
def simple_communities(simple_graph):
    from graphify_sf.cluster import cluster

    return cluster(simple_graph)
