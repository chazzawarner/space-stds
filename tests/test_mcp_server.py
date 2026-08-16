from pathlib import Path

import pytest
from mcp import Client

from space_stds.domain import IngestRequest
from space_stds.server import create_server
from space_stds.service import StandardsService
from tests.pdf_factory import write_text_pdf


@pytest.mark.anyio
async def test_mcp_client_can_search_and_read_resource(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    source = corpus / "ecss.pdf"
    write_text_pdf(source, [["6.3 Verification", "Verification shall use objective evidence."]])
    service = StandardsService(tmp_path / "index.db", corpus)
    service.ingest(
        IngestRequest(
            source="ECSS",
            document_id="ECSS-E-ST-10-02C",
            title="Verification",
            revision="1",
            status="active",
            official_url="https://ecss.nl/example.pdf",
            path=source,
        )
    )

    async with Client(create_server(service), raise_exceptions=True) as client:
        result = await client.call_tool("search_standards", {"query": "objective evidence"})

        assert result.structured_content is not None
        hits = result.structured_content["result"]
        assert hits[0]["document_id"] == "ECSS-E-ST-10-02C"
        resource = await client.read_resource(hits[0]["resource_uri"])
        assert "objective evidence" in resource.contents[0].text

        document_result = await client.call_tool(
            "get_document", {"document_id": "ECSS-E-ST-10-02C", "revision": "1"}
        )
        assert document_result.structured_content is not None
        assert document_result.structured_content["document_id"] == "ECSS-E-ST-10-02C"
        document_resource = await client.read_resource(
            document_result.structured_content["resource_uri"]
        )
        assert "Synthetic" not in document_resource.contents[0].text
        assert "Verification" in document_resource.contents[0].text
