from bidgate.adapters.llm import ChunkedReader, RuleReader
from bidgate.adapters.markovian import MarkovianReader, node_binary
from bidgate.infrastructure.wiring import build_reader


def test_no_url_means_rules_reader():
    assert isinstance(build_reader({}), RuleReader)


def test_chunked_switch():
    assert isinstance(build_reader({"BIDGATE_LLM_BASE_URL": "http://x/v1", "BIDGATE_LLM_READER": "chunked"}), ChunkedReader)


def test_markovian_is_default_with_url():
    r = build_reader({"BIDGATE_LLM_BASE_URL": "http://x/v1"})
    assert isinstance(r, MarkovianReader if node_binary() else ChunkedReader)
