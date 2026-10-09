"""Chroma 本地快照适配；显式向量、独占构建和原子指针，不默认下载模型或删除旧库。"""

import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import cast
from uuid import uuid4

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.api.types import Embedding, Metadata, OneOrMany
from chromadb.config import Settings
from pydantic import ValidationError

from .domain import (
    BuildResult,
    IndexManifest,
    KnowledgeChunk,
    KnowledgeError,
    SearchHit,
    chunk_digest,
)

COLLECTION = "odm-knowledge"


class ChromaIndex:
    """管理小语料的本地不可变快照，不是多机向量服务或业务数据库。"""

    def __init__(self, resource_root: Path):
        """保存资源路径；构造不创建空索引。"""
        self._indexes = resource_root / "indexes"
        self._artifacts = resource_root / "artifacts"
        self._collections: dict[str, Collection] = {}

    def _collection(self, manifest: IndexManifest) -> Collection:
        cached = self._collections.get(manifest.snapshot)
        if cached is not None:
            return cached
        path = self._indexes / manifest.snapshot / "chroma"
        if not (path / "chroma.sqlite3").is_file():
            raise KnowledgeError("索引缺失或不完整，不能自动创建空库")
        try:
            client = chromadb.PersistentClient(
                str(path), settings=Settings(anonymized_telemetry=False)
            )
            collection = client.get_collection(COLLECTION, embedding_function=None)
            self._collections[manifest.snapshot] = collection
            return collection
        except (chromadb.errors.ChromaError, ValueError) as error:
            raise KnowledgeError("索引集合无法读取") from error

    def _read_manifest(self, path: Path) -> IndexManifest:
        try:
            manifest = IndexManifest.model_validate_json(path.read_text(encoding="utf-8"))
            if manifest.snapshot != path.parent.name:
                raise KnowledgeError("索引清单路径不一致")
            return manifest
        except (OSError, ValidationError) as error:
            raise KnowledgeError("索引清单缺失或不完整") from error

    def _validate(self, manifest: IndexManifest, signature: str) -> Collection:
        if manifest.model_signature != signature:
            raise KnowledgeError("模型与索引不兼容，请显式重新构建")
        collection = self._collection(manifest)
        stored = collection.get(include=["documents", "metadatas", "embeddings"])
        ids, texts, metadata, vectors = (
            stored["ids"],
            stored["documents"],
            stored["metadatas"],
            stored["embeddings"],
        )
        if (
            len(ids) != len(manifest.chunk_ids)
            or set(ids) != set(manifest.chunk_ids)
            or texts is None
            or metadata is None
            or vectors is None
        ):
            raise KnowledgeError("索引片段数量或标识不完整")
        digests = dict(zip(manifest.chunk_ids, manifest.chunk_digests, strict=True))
        for chunk_id, text, meta, vector in zip(ids, texts, metadata, vectors, strict=True):
            try:
                chunk = KnowledgeChunk.model_validate({**(meta or {}), "text": text})
            except ValidationError as error:
                raise KnowledgeError("索引来源不完整") from error
            if chunk_digest(chunk) != digests[chunk_id]:
                raise KnowledgeError("索引来源与片段摘要错配")
            if (
                chunk.chunk_id != chunk_id
                or hashlib.sha256(chunk.text.encode()).hexdigest() != chunk.content_hash
                or len(vector) != manifest.dimensions
                or not all(math.isfinite(float(value)) for value in vector)
                or sum(float(value) ** 2 for value in vector) <= 0
            ):
                raise KnowledgeError("索引内容或向量不完整")
        return collection

    def _find(self, fingerprint: str, signature: str) -> IndexManifest | None:
        for path in sorted(self._indexes.glob(f"{fingerprint}-*/manifest.json")):
            manifest = self._read_manifest(path)
            self._validate(manifest, signature)
            return manifest
        return None

    def find(self, fingerprint: str, signature: str) -> IndexManifest | None:
        """查找完整快照；持有其他构建锁时拒绝新构建。

        Args:
            fingerprint: 当前来源、模型及切分指纹。
            signature: 当前模型签名。
        Returns:
            可复用快照，或 None。
        Raises:
            KnowledgeError: 已有构建任务或索引损坏。
        """
        if (self._indexes / ".build.lock").exists():
            raise KnowledgeError("存在构建锁，请确认没有其他构建进程；异常退出需人工核对后移除锁")
        return self._find(fingerprint, signature)

    def _activate(self, snapshot: str) -> None:
        temporary = self._indexes / f".current-{uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps({"snapshot": snapshot}), encoding="utf-8")
            os.replace(temporary, self._indexes / "current.json")
        finally:
            temporary.unlink(missing_ok=True)

    def _verify_in_subprocess(self, manifest: IndexManifest, pending: bool = False) -> None:
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "odmflow.knowledge.snapshot_validation",
                    str(self._indexes.parent),
                    manifest.snapshot,
                    manifest.model_signature,
                    *(["--pending"] if pending else []),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise KnowledgeError("索引独立进程核验超时，未发布新版本") from error
        if result.returncode != 0:
            raise KnowledgeError("索引独立进程核验失败，未发布新版本")

    def verify_snapshot(self, snapshot: str, signature: str, pending: bool = False) -> None:
        """独立核验指定快照与可查询性，不改变当前指针。

        Args:
            snapshot: 受控版本目录名。
            signature: 模型签名。
            pending: 是否读取尚未发布的清单。
        Raises:
            KnowledgeError: 来源、维度或持久集合不完整。
        """
        if not re.fullmatch(r"[0-9a-f]{64}-[0-9a-f]{8}", snapshot):
            raise KnowledgeError("索引版本名无效")
        name = "manifest.pending.json" if pending else "manifest.json"
        manifest = self._read_manifest(self._indexes / snapshot / name)
        collection = self._validate(manifest, signature)
        stored = collection.get(ids=[manifest.chunk_ids[0]], include=["embeddings"])
        vectors = stored["embeddings"]
        if vectors is None:
            raise KnowledgeError("索引没有可查询向量")
        if not self.query(manifest, [float(value) for value in vectors[0]], 1):
            raise KnowledgeError("索引不能查询")

    def publish(
        self,
        manifest: IndexManifest,
        chunks: tuple[KnowledgeChunk, ...],
        vectors: list[list[float]],
    ) -> BuildResult:
        """写新快照、重新读取核验后发布；失败保留旧指针。

        Args:
            manifest: 新快照来源清单。
            chunks: 原文片段。
            vectors: 对应向量；复用时可以为空。
        Returns:
            已激活快照及是否复用。
        Raises:
            KnowledgeError: 构建锁、兼容或完整性错误；I/O 错误由 CLI 显示。
        """
        self._indexes.mkdir(parents=True, exist_ok=True)
        lock = self._indexes / ".build.lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise KnowledgeError("存在构建锁，不能同时发布") from error
        os.close(descriptor)
        try:
            existing = self._find(manifest.fingerprint, manifest.model_signature)
            if existing:
                self._verify_in_subprocess(existing)
                self._activate(existing.snapshot)
                return BuildResult(manifest=existing, reused=True)
            directory = self._indexes / manifest.snapshot
            directory.mkdir()
            client = chromadb.PersistentClient(
                str(directory / "chroma"), settings=Settings(anonymized_telemetry=False)
            )
            collection = client.create_collection(
                COLLECTION,
                embedding_function=None,
                configuration={"hnsw": {"space": "cosine"}},
            )
            collection.add(
                ids=[chunk.chunk_id for chunk in chunks],
                embeddings=cast(OneOrMany[Embedding], vectors),
                documents=[chunk.text for chunk in chunks],
                metadatas=[cast(Metadata, chunk.model_dump(exclude={"text"})) for chunk in chunks],
            )
            self._validate(manifest, manifest.model_signature)
            preview = "\n".join(chunk.model_dump_json() for chunk in chunks) + "\n"
            report = self._artifacts / manifest.snapshot
            report.mkdir(parents=True)
            (report / "chunks.jsonl").write_text(preview, encoding="utf-8")
            (report / "build.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
            # 先写待验证清单；独立进程通过前不产生可复用的完成标记。
            (directory / "manifest.pending.json").write_text(
                manifest.model_dump_json(indent=2), encoding="utf-8"
            )
            self._verify_in_subprocess(manifest, pending=True)
            os.replace(directory / "manifest.pending.json", directory / "manifest.json")
            self._activate(manifest.snapshot)
            return BuildResult(manifest=manifest, reused=False)
        finally:
            lock.unlink()

    def current(self, signature: str) -> IndexManifest:
        """读取当前有效索引；不创建目录或空集合。

        Args:
            signature: 调用方编码签名。
        Returns:
            核验后的当前快照。
        Raises:
            KnowledgeError: 缺库、坏清单或不兼容。
        """
        try:
            pointer = json.loads((self._indexes / "current.json").read_text(encoding="utf-8"))
            snapshot = pointer["snapshot"]
            if not isinstance(snapshot, str) or not re.fullmatch(
                r"[0-9a-f]{64}-[0-9a-f]{8}", snapshot
            ):
                raise KnowledgeError("索引指针不合法")
            manifest = self._read_manifest(self._indexes / snapshot / "manifest.json")
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise KnowledgeError("当前索引不存在或指针不完整，请先 build") from error
        self._validate(manifest, signature)
        return manifest

    def read_chunks(self, manifest: IndexManifest) -> tuple[KnowledgeChunk, ...]:
        """按清单顺序返回指定快照片段，不能把其他快照混作评测分母。

        Args:
            manifest: 已完成的快照清单。
        Returns:
            核验后带原文和来源的完整片段。
        Raises:
            KnowledgeError: 快照或来源完整性校验失败。
        """
        collection = self._validate(manifest, manifest.model_signature)
        stored = collection.get(include=["documents", "metadatas"])
        texts, metadata = stored["documents"], stored["metadatas"]
        if texts is None or metadata is None:
            raise KnowledgeError("评测索引片段不完整")
        chunks = {
            chunk_id: KnowledgeChunk.model_validate({**(meta or {}), "text": text})
            for chunk_id, text, meta in zip(stored["ids"], texts, metadata, strict=True)
        }
        return tuple(chunks[chunk_id] for chunk_id in manifest.chunk_ids)

    def query(
        self, manifest: IndexManifest, vector: list[float], top_k: int
    ) -> tuple[SearchHit, ...]:
        """对不可变快照查询显式向量并还原来源，不执行默认 Embedding。

        Args:
            manifest: 已验证快照。
            vector: 编码后的查询。
            top_k: 请求候选条数。
        Returns:
            原文和未校准 cosine 距离。
        """
        result = self._collection(manifest).query(
            query_embeddings=cast(OneOrMany[Embedding], [vector]),
            n_results=min(top_k, len(manifest.chunk_ids)),
            include=["documents", "metadatas", "distances"],
        )
        texts, metadata, distances = result["documents"], result["metadatas"], result["distances"]
        if texts is None or metadata is None or distances is None:
            raise KnowledgeError("检索结果不完整")
        return tuple(
            SearchHit(
                chunk=KnowledgeChunk.model_validate({**(meta or {}), "text": text}),
                distance=distance,
            )
            for text, meta, distance in zip(texts[0], metadata[0], distances[0], strict=True)
        )
