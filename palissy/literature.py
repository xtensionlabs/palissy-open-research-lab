"""Tavily literature search, logged as provenance records."""

import asyncio
import time

from tavily import TavilyClient

from .provenance import ProvenanceLog, ProvenanceRecord


class Literature:
    def __init__(self, api_key: str, log: ProvenanceLog):
        self.client = TavilyClient(api_key=api_key)
        self.log = log

    async def search(self, query: str, *, max_results: int = 5, depth: str = "advanced"):
        start = time.perf_counter()
        resp = await asyncio.to_thread(
            self.client.search, query=query, search_depth=depth, max_results=max_results
        )
        latency = time.perf_counter() - start
        results = resp.get("results", [])
        record = self.log.add(ProvenanceRecord(
            kind="search",
            stage="literature",
            summary=f"{len(results)} results for: {query}",
            inputs={"query": query, "depth": depth, "max_results": max_results},
            outputs={"results": [
                {"title": r.get("title"), "url": r.get("url"), "content": r.get("content")}
                for r in results
            ]},
            latency_s=latency,
            sources=[r["url"] for r in results if r.get("url")],
        ))
        return results, record

    async def extract(self, urls: list[str]):
        start = time.perf_counter()
        resp = await asyncio.to_thread(self.client.extract, urls=urls)
        latency = time.perf_counter() - start
        results = resp.get("results", [])
        record = self.log.add(ProvenanceRecord(
            kind="extract",
            stage="literature",
            summary=f"extracted {len(results)}/{len(urls)} pages",
            inputs={"urls": urls},
            outputs={"results": [
                {"url": r.get("url"), "raw_content": (r.get("raw_content") or "")[:5000]}
                for r in results
            ]},
            latency_s=latency,
            sources=urls,
        ))
        return results, record
