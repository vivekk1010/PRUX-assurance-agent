"""Read-only ingestion for PRDs, Figma, Confluence, Jira, and ordinary web pages."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import httpx

from requirements_alchemist.config import Settings
from requirements_alchemist.models import SourceDocument, SourceKind


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, _attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _plain_html(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return re.sub(r"\n{3,}", "\n\n", " ".join(parser.parts).strip())


def _flatten_adf(node) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_flatten_adf(item) for item in node)
    if not isinstance(node, dict):
        return ""
    text = str(node.get("text", ""))
    content = _flatten_adf(node.get("content", []))
    suffix = "\n" if node.get("type") in {"paragraph", "heading", "listItem"} else ""
    return text + content + suffix


def _source_id(kind: SourceKind, value: str) -> str:
    return f"{kind.value}-{hashlib.sha256(value.encode()).hexdigest()[:12]}"


def text_document(title: str, text: str, kind: SourceKind = SourceKind.PRD) -> SourceDocument:
    clean = text.strip()
    return SourceDocument(
        id=_source_id(kind, f"{title}\n{clean}"),
        kind=kind,
        title=title.strip() or "Untitled source",
        text=clean,
    )


class SourceLoader:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _validate_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Source URLs must use HTTPS")
        host = parsed.hostname.lower()
        allowed = {"www.figma.com", "figma.com"} | set(
            self.settings.allowed_source_hosts
        )
        configured = urlparse(self.settings.atlassian_base_url).hostname
        if configured:
            allowed.add(configured.lower())
        if host not in allowed:
            raise ValueError(f"Source host is not allowed: {host}")
        for address in socket.getaddrinfo(host, 443):
            ip = ipaddress.ip_address(address[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise ValueError("Private or reserved source addresses are not allowed")
        return url

    def _atlassian_auth(self) -> tuple[str, str]:
        email = os.getenv(self.settings.atlassian_email_env, "")
        token = os.getenv(self.settings.atlassian_token_env, "")
        if not email or not token:
            raise ValueError("Atlassian email and API token are required")
        return email, token

    def _request(
        self,
        url: str,
        *,
        auth: tuple[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30,
    ) -> tuple[bytes, str]:
        chunks: list[bytes] = []
        size = 0
        with httpx.stream(
            "GET",
            url,
            auth=auth,
            headers=headers,
            follow_redirects=False,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError("Source redirects are not allowed")
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self.settings.source_max_download_bytes:
                    raise ValueError("Source response exceeds the configured download limit")
                chunks.append(chunk)
            return b"".join(chunks), response.headers.get("content-type", "")

    def load_url(self, url: str) -> SourceDocument:
        url = self._validate_url(url.strip())
        parsed = urlparse(url)
        if "figma.com" in parsed.hostname:
            return self.load_figma(url)
        if self.settings.atlassian_base_url and parsed.hostname == urlparse(
            self.settings.atlassian_base_url
        ).hostname:
            if "/browse/" in parsed.path:
                return self.load_jira(url)
            if "/wiki/" in parsed.path:
                return self.load_confluence(url)
        content, content_type = self._request(url)
        if "json" in content_type:
            text = json.dumps(json.loads(content), indent=2)
        else:
            decoded = content.decode("utf-8", errors="replace")
            text = _plain_html(decoded) if "html" in content_type else decoded
        text = text[: self.settings.source_max_chars]
        return SourceDocument(
            id=_source_id(SourceKind.PRD, url),
            kind=SourceKind.PRD,
            title=parsed.path.rsplit("/", 1)[-1] or parsed.hostname,
            text=text,
            url=url,
        )

    def load_confluence(self, url: str) -> SourceDocument:
        match = re.search(r"/pages/(\d+)", url)
        page_id = match.group(1) if match else parse_qs(urlparse(url).query).get("pageId", [""])[0]
        if not page_id:
            raise ValueError("Could not determine the Confluence page id")
        endpoint = (
            f"{self.settings.atlassian_base_url.rstrip('/')}/wiki/api/v2/pages/{page_id}"
            "?body-format=storage"
        )
        content, _ = self._request(endpoint, auth=self._atlassian_auth())
        payload = json.loads(content)
        storage = payload.get("body", {}).get("storage", {}).get("value", "")
        return SourceDocument(
            id=f"confluence-{page_id}",
            kind=SourceKind.CONFLUENCE,
            title=payload.get("title", f"Confluence page {page_id}"),
            text=_plain_html(storage)[: self.settings.source_max_chars],
            url=url,
            metadata={"page_id": page_id, "version": payload.get("version", {}).get("number")},
        )

    def load_jira(self, url: str) -> SourceDocument:
        match = re.search(r"/browse/([A-Z][A-Z0-9_]+-\d+)", url, re.I)
        if not match:
            raise ValueError("Could not determine the Jira issue key")
        key = match.group(1).upper()
        endpoint = (
            f"{self.settings.atlassian_base_url.rstrip('/')}/rest/api/3/issue/{key}"
            "?fields=summary,description,issuetype,status,priority,labels,parent,subtasks"
        )
        content, _ = self._request(endpoint, auth=self._atlassian_auth())
        fields = json.loads(content).get("fields", {})
        text = "\n".join(
            [
                f"Summary: {fields.get('summary', '')}",
                f"Type: {(fields.get('issuetype') or {}).get('name', '')}",
                f"Status: {(fields.get('status') or {}).get('name', '')}",
                f"Priority: {(fields.get('priority') or {}).get('name', '')}",
                f"Labels: {', '.join(fields.get('labels') or [])}",
                "Description:",
                _flatten_adf(fields.get("description")),
            ]
        )
        return SourceDocument(
            id=f"jira-{key.lower()}",
            kind=SourceKind.JIRA,
            title=f"{key}: {fields.get('summary', '')}",
            text=text[: self.settings.source_max_chars],
            url=url,
            metadata={"issue_key": key},
        )

    def load_figma(self, url: str) -> SourceDocument:
        match = re.search(r"figma\.com/(?:file|design)/([A-Za-z0-9_-]+)", url)
        if not match:
            raise ValueError("Could not determine the Figma file key")
        token = os.getenv(self.settings.figma_token_env, "")
        if not token:
            raise ValueError(f"{self.settings.figma_token_env} is required")
        file_key = match.group(1)
        content, _ = self._request(
            f"https://api.figma.com/v1/files/{file_key}",
            headers={"X-Figma-Token": token},
            timeout=45,
        )
        payload = json.loads(content)
        lines: list[str] = []

        def walk(node: dict, depth: int = 0):
            name = str(node.get("name", "")).strip()
            node_type = node.get("type", "")
            characters = str(node.get("characters", "")).strip()
            if name or characters:
                lines.append(
                    f"{'  ' * min(depth, 5)}[{node_type}] {name}"
                    + (f": {characters}" if characters else "")
                )
            for child in node.get("children", []):
                walk(child, depth + 1)

        walk(payload.get("document", {}))
        return SourceDocument(
            id=f"figma-{file_key}",
            kind=SourceKind.FIGMA,
            title=payload.get("name", f"Figma {file_key}"),
            text="\n".join(lines)[: self.settings.source_max_chars],
            url=url,
            metadata={
                "file_key": file_key,
                "version": payload.get("version"),
                "last_modified": payload.get("lastModified"),
            },
        )
