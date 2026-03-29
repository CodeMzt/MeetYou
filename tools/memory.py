"""
记忆图谱核心管理模块。

基于 NetworkX 图结构 + 语义向量嵌入，实现：
- 记忆的持久化存储与检索
- 基于余弦相似度的突触（边）关联
- 指数衰减遗忘机制
- 情绪强度调制
"""

import hashlib
import os
import json
import logging

import aiohttp
import networkx as nx
import numpy as np

logger = logging.getLogger("meetyou.memory")


class Memory:
    """
    系统记忆核心管理类。

    利用 NetworkX 图结构存储记忆节点，通过向量嵌入和余弦相似度
    构建突触关联，支持遗忘衰减和联想检索。
    """

    def __init__(self):
        self._memory_file_path = "memory.json"
        self._embedding_model = ""
        self._embedding_api_key = ""
        self._embedding_api_url = ""
        self._memory_net: nx.Graph | None = None
        self._http_session: aiohttp.ClientSession | None = None

    # ============================================================
    # 初始化与关闭
    # ============================================================

    async def init_memory(self, config):
        """
        初始化记忆系统。

        Args:
            config: ConfigManager 实例
        """
        self._memory_file_path = config.get("memory_file_path") or self._memory_file_path
        self._embedding_model = config.get("embedding_model") or ""
        self._embedding_api_key = config.get("embedding_api_key") or ""
        self._embedding_api_url = config.get("embedding_api_url") or ""
        self._http_session = aiohttp.ClientSession()

        # 加载图谱
        self._memory_net = nx.Graph()
        if os.path.exists(self._memory_file_path):
            try:
                with open(self._memory_file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if content.strip():
                        graph_data = json.loads(content)
                        self._memory_net = nx.node_link_graph(graph_data, edges="edges")
            except Exception as e:
                logger.error(f"加载记忆图谱失败: {e}")
                self._memory_net = nx.Graph()

        self.build_synapses()
        self.fade_memory()
        logger.info(f"记忆系统初始化完成: {self._memory_net.number_of_nodes()} 个节点")

    async def close_memory(self):
        """关闭 HTTP session"""
        if self._http_session:
            await self._http_session.close()
            self._http_session = None

    # ============================================================
    # 内部工具（同步）
    # ============================================================

    @staticmethod
    def _generate_node_id(text_content: str) -> str:
        """SHA-256 前 16 位作为节点 ID"""
        return hashlib.sha256(text_content.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _calc_cosine(vec1, vec2) -> float:
        """计算两个向量的余弦相似度（同步）"""
        n1 = np.linalg.norm(vec1)
        n2 = np.linalg.norm(vec2)
        if n1 == 0 or n2 == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (n1 * n2))

    # ============================================================
    # Embedding（异步 - 需要网络）
    # ============================================================

    async def _get_embedding(self, text: str) -> list:
        """调用 Embedding API 获取文本向量。复用 HTTP session。"""
        if self._http_session is None:
            logger.error("HTTP session 未初始化")
            return []

        headers = {
            "Authorization": f"Bearer {self._embedding_api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self._embedding_model, "input": text}

        try:
            async with self._http_session.post(
                self._embedding_api_url, headers=headers, json=payload
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                # 兼容多种返回格式
                embedding = data.get("embedding")
                if isinstance(embedding, list):
                    return embedding
                items = data.get("data", [])
                if isinstance(items, list) and items:
                    first = items[0] if isinstance(items[0], dict) else {}
                    embedding = first.get("embedding")
                    if isinstance(embedding, list):
                        return embedding
            return []
        except Exception as e:
            logger.error(f"获取 embedding 失败: {e}")
            return []

    # ============================================================
    # 突触构建（同步 - 纯计算）
    # ============================================================

    def build_synapses(self):
        """
        全量批次突触构建 — 使用 NumPy 矩阵批量计算。

        O(N²) 次相似度计算优化为单次矩阵乘法 S = M̂·M̂ᵀ。
        """
        all_nodes = list(self._memory_net.nodes(data=True))
        if len(all_nodes) < 2:
            return

        ids = []
        vectors = []
        for node_id, data in all_nodes:
            vec = data.get("vector")
            if vec and len(vec) > 0:
                ids.append(node_id)
                vectors.append(vec)

        if len(ids) < 2:
            return

        mat = np.array(vectors, dtype=np.float32)
        # L2 归一化
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized = mat / norms

        # 矩阵乘法得到相似度矩阵
        sim_matrix = normalized @ normalized.T

        # 遍历上三角，阈值 0.8
        n = len(ids)
        rows, cols = np.where(
            np.triu(sim_matrix, k=1) > 0.8
        )
        new_edges = 0
        for r, c in zip(rows, cols):
            self._memory_net.add_edge(ids[r], ids[c], sim_weight=float(sim_matrix[r, c]))
            new_edges += 1

        if new_edges > 0:
            logger.info(f"突触构建完成: 新建 {new_edges} 条关联")

    def rebuild_synapses(self, new_id: str):
        """
        增量突触构建 — 新节点对所有现有节点计算相似度。

        使用较高阈值 0.8 确保实时操作仅建立高置信度关联。
        """
        new_vec = self._memory_net.nodes[new_id].get("vector")
        if not new_vec:
            return

        new_vec = np.array(new_vec, dtype=np.float32)
        new_norm = np.linalg.norm(new_vec)
        if new_norm == 0:
            return
        new_vec_normalized = new_vec / new_norm

        for node_id, data in self._memory_net.nodes(data=True):
            if node_id == new_id:
                continue
            vec = data.get("vector")
            if not vec:
                continue
            vec = np.array(vec, dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm == 0:
                continue
            sim = float(np.dot(new_vec_normalized, vec / norm))
            if sim > 0.8:
                self._memory_net.add_edge(node_id, new_id, sim_weight=sim)

    # ============================================================
    # 遗忘衰减（同步）
    # ============================================================

    def fade_memory(self):
        """
        执行一轮指数衰减遗忘。

        λ = 0.95，低于阈值 0.2 的节点被永久移除。
        """
        to_remove = []
        for node_id, data in self._memory_net.nodes(data=True):
            w = data.get("memory_weight", 0.0)
            self._memory_net.nodes[node_id]["memory_weight"] = w * 0.95
            if w <= 0.2:
                to_remove.append(node_id)

        for node_id in to_remove:
            self._memory_net.remove_node(node_id)

        if to_remove:
            logger.info(f"记忆衰减: 移除 {len(to_remove)} 个节点")

    # ============================================================
    # 检索
    # ============================================================

    async def retrieve_memory_net(self, target_node_id, search_depth=3, min_weight_threshold=0.5):
        """沿图扩散检索关联记忆"""
        if not self._memory_net.has_node(target_node_id):
            return []

        sub_graph = nx.ego_graph(self._memory_net, target_node_id, radius=search_depth)
        extracted = []

        for node_id, data in sub_graph.nodes(data=True):
            w = data.get("memory_weight", 0.0)
            ei = data.get("emotion_intensity", 1.0)
            if w >= min_weight_threshold:
                extracted.append({
                    "content": data.get("content"),
                    "weight": w,
                    "emotion_intensity": ei,
                })
                self._memory_net.nodes[node_id]["memory_weight"] += 10 * ei / (1 + w)

        return extracted

    # ============================================================
    # 持久化
    # ============================================================

    async def save_memory_graph(self):
        """将图谱序列化到 JSON 文件"""
        graph_data = nx.node_link_data(self._memory_net, edges="edges")
        with open(self._memory_file_path, "w", encoding="utf-8") as f:
            json.dump(graph_data, f, ensure_ascii=False)

    # ============================================================
    # 对外接口（LLM 工具调用）
    # ============================================================

    async def save_memory(self, memory_text: str, text_emotion_intensity: float = 1.0) -> str:
        """保存新记忆到图谱"""
        embedding = await self._get_embedding(memory_text)
        if not embedding:
            return "获取内容向量失败"

        node_id = self._generate_node_id(memory_text)
        if node_id in self._memory_net.nodes:
            return f"记忆已存在, id={node_id}"

        initial_weight = 0.5 + text_emotion_intensity * 0.5
        self._memory_net.add_node(
            node_id,
            content=memory_text,
            vector=embedding,
            memory_weight=initial_weight,
            emotion_intensity=text_emotion_intensity,
        )
        self.rebuild_synapses(node_id)
        await self.save_memory_graph()
        return f"成功保存记忆, id={node_id}"

    async def update_memory(self, nodeid: str, text: str) -> str:
        """更新指定节点的记忆内容"""
        embedding = await self._get_embedding(text)
        if not embedding:
            return "获取内容向量失败"

        if nodeid not in self._memory_net.nodes:
            self._memory_net.add_node(
                nodeid, content=text, vector=embedding,
                memory_weight=10, emotion_intensity=0.5,
            )
        else:
            self._memory_net.nodes[nodeid]["content"] = text
            self._memory_net.nodes[nodeid]["vector"] = embedding
        await self.save_memory_graph()
        return f"成功更新记忆, id={nodeid}"

    async def recall_memory(self, query_text: str) -> str:
        """语义检索记忆"""
        self.fade_memory()
        embedding = await self._get_embedding(query_text)
        if not embedding:
            return "获取内容向量失败"

        # 全局向量检索锚点
        best_id = None
        best_score = -1.0
        query_vec = np.array(embedding, dtype=np.float32)

        for node_id, data in self._memory_net.nodes(data=True):
            vec = data.get("vector")
            if vec:
                score = self._calc_cosine(query_vec, np.array(vec, dtype=np.float32))
                if score > best_score:
                    best_score = score
                    best_id = node_id

        if best_id is None or best_score < 0.4:
            return "未找到相关记忆"

        recall_info = await self.retrieve_memory_net(best_id, search_depth=3, min_weight_threshold=0.4)
        if not recall_info:
            return "未找到相关记忆"

        lines = []
        for i, info in enumerate(recall_info, 1):
            lines.append(
                f"[记忆 #{i}] (强度:{info['weight']:.2f}, 情绪:{info['emotion_intensity']:.2f})\n"
                f"{info['content']}"
            )

        await self.save_memory_graph()
        return "\n\n".join(lines)
