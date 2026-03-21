import hashlib
import aiohttp
import os
import json
import networkx as nx
import numpy as np
# from core.sensors import listener_instance
# from core.manager import ConfigManager

class Memory:
    """
    系统记忆核心管理类。
    利用 NetworkX 图结构，将文本记忆片段持久化并向量化，支持构建突触关联以及基于强度的记忆消退与检索。
    """
    def __init__(self):
        """初始化记忆管理器的局部状态参数和图结构指针。"""
        self._memory_file_path = "memory.json"
        self._embedding_model = ''
        self._embedding_api_key = ''
        self._embedding_api_url = ''
        self._memory_net = None

    def _system_output(self, msg):
        from core.sensors import listener_instance
        listener_instance.system_output(msg)

    def _generate_node_id(self, text_content):
        # 使用 SHA-256 哈希函数
        hash_obj = hashlib.sha256(text_content.encode('utf-8'))
        # 取前 16 个字符作为节点 ID
        return hash_obj.hexdigest()[:16]
        
    async def _get_embedding(self, text: str):
        headers = {
            "Authorization": f"Bearer {self._embedding_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self._embedding_model,
            "input": text
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self._embedding_api_url, headers=headers, json=payload) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    embedding = data.get('embedding')
                    if isinstance(embedding, list):
                        return embedding
                    items = data.get('data', [])
                    if isinstance(items, list) and items:
                        first = items[0] or {}
                        if isinstance(first, dict):
                            embedding = first.get('embedding')
                            if isinstance(embedding, list):
                                return embedding
                return []
        except Exception as e:
            self._system_output(f"[tool] [memory] [Error]: 获取记忆向量失败: {e}")
            return []

    async def _calc_cosine(self, embedding1: list, embedding2: list):
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return np.dot(embedding1, embedding2) / (norm1 * norm2)

    async def fade_memory(self):
        id_to_fade = []
        for node_id, node_data in self._memory_net.nodes(data=True):
            current_weight = node_data.get("memory_weight", 0.0)
            self._memory_net.nodes[node_id]["memory_weight"] = current_weight * 0.95
            if(current_weight <= 0.2):
                id_to_fade.append(node_id)

        for node_id in id_to_fade:
            self._memory_net.remove_node(node_id)

    async def retrieve_memory_net(self, target_node_id, search_depth=3, min_weight_threshold=0.5):
        if not self._memory_net.has_node(target_node_id):
            return []
        # 向外扩散 search_depth 步的子图
        sub_graph = nx.ego_graph(self._memory_net, target_node_id, radius=search_depth)
        
        extracted_info = []
        max_weight = max((d.get("memory_weight", 1.0) for _, d in sub_graph.nodes(data=True)), default=1.0)
        # 遍历这个被抠出来的局部网络
        for node_id, node_data in sub_graph.nodes(data=True):
            current_weight = node_data.get("memory_weight", 0.0)
            emotion_intensity = node_data.get("emotion_intensity", 1.0)
            
            if current_weight >= min_weight_threshold:
                extracted_info.append({
                    "content": node_data.get("content"),
                    "weight": current_weight,
                    "emotion_intensity": emotion_intensity
                })
                self._memory_net.nodes[node_id]["memory_weight"] += 10 * emotion_intensity / (1+current_weight)
                
        return extracted_info

    async def save_memory_graph(self):
        graph_data = nx.node_link_data(self._memory_net, edges = 'edges')
        with open(self._memory_file_path, "w",encoding="utf-8") as f:
            json.dump(graph_data, f, ensure_ascii=False)

    async def build_synapses(self):
        all_nodes = list(self._memory_net.nodes(data=True))
        
        # 双重循环比对 (O(N^2) 复杂度，必须在睡觉时做)
        for i in range(len(all_nodes)):
            for j in range(i + 1, len(all_nodes)):
                node_i_id, data_i = all_nodes[i]
                node_j_id, data_j = all_nodes[j]
                
                sim_score = await self._calc_cosine(data_i["vector"], data_j["vector"])
                
                if sim_score > 0.80:
                    pass
                if sim_score > 0.70:
                    # add_edge 会在这两个节点间连线，我们把相似度作为这条线的权重
                    self._memory_net.add_edge(node_i_id, node_j_id, sim_weight=sim_score)
                    self._system_output(f"[tool] [memory] [Info] [神经突触]: 节点 {node_i_id} 与 {node_j_id} 建立关联 (相似度: {sim_score:.2f})")

    async def rebuild_synapses(self, new_id: str):
        all_nodes = list(self._memory_net.nodes(data=True))

        for i in range(len(all_nodes)):
            node_i_id, data_i = all_nodes[i]
            sim_score = await self._calc_cosine(data_i["vector"], self._memory_net.nodes[new_id]["vector"])
            if sim_score > 0.7:
                self._memory_net.add_edge(node_i_id, new_id, sim_weight=sim_score)
                self._system_output(f"[tool] [memory] [Info] [神经突触]: 节点 {node_i_id} 与 {new_id} 建立关联 (相似度: {sim_score:.2f})")

    async def init_memory(self):
        from core.manager import cfg as config_manager
        self._memory_file_path = config_manager.get_config_item("memory_file_path")
        self._embedding_model = config_manager.get_config_item("embedding_model")
        self._embedding_api_key = config_manager.get_config_item("embedding_api_key")
        self._embedding_api_url = config_manager.get_config_item("embedding_api_url")
        
        self._memory_net = nx.Graph()
        graph_data = None
        if os.path.exists(self._memory_file_path):
            with open(self._memory_file_path, "r",encoding="utf-8") as f:
                content = f.read()
                if content != "":
                    graph_data = json.loads(content)

        if graph_data:
            self._memory_net = nx.node_link_graph(graph_data, edges = 'edges')

        await self.build_synapses()
        await self.fade_memory()

    async def save_memory(self, memory_text: str, text_emotion_intensity: float = 1.0):
        """
        保存新的文本到记忆图谱，并包含情绪强度考量，异步触发节点间的向量相似度突触构建。
        
        Args:
            memory_text (str): 记忆的核心文本内容。
            text_emotion_intensity (float): 记忆附带的情绪强度值，默认为 1.0。
            
        Returns:
            str: 保存结果提示字符串（包含了节点 ID 或失败标识）。
        """
        embedding = await self._get_embedding(memory_text)
        if not embedding:
            return '获取内容向量失败'
        
        node_id = self._generate_node_id(memory_text)
        if node_id in self._memory_net.nodes:
            return f'记忆已存在,id={node_id}'
        initial_weight = 0.5 + text_emotion_intensity * 0.5
        self._memory_net.add_node(
            node_id,
            content=memory_text,
            vector=embedding,
            memory_weight=initial_weight,
            emotion_intensity=text_emotion_intensity
        )
        await self.rebuild_synapses(node_id)
        await self.save_memory_graph()
        return f'成功保存记忆,id={node_id}'

    async def update_memory(self, nodeid: str, text: str):
        """
        根据节点 ID 异步更新指定的记忆节点内容，并重新生成对应的特征向量。
        
        Args:
            nodeid (str): 目标记忆节点的 ID。
            text (str): 要更新成的新文本内容。
            
        Returns:
            str: 更新成功的反馈信息。
        """
        embedding = await self._get_embedding(text)
        if not embedding:
            return '获取内容向量失败'
        
        if nodeid not in self._memory_net.nodes:
            self._memory_net.add_node(nodeid, content=text, vector=embedding, memory_weight=10, emotion_intensity=0.5)
        else:
            self._memory_net.nodes[nodeid]["content"] = text
            self._memory_net.nodes[nodeid]["vector"] = embedding
        await self.save_memory_graph()
        return f'成功更新记忆,id={nodeid}'

    async def recall_memory(self, query_text: str):
        """
        根据查询文本，搜索并在图谱中异步提取相关联的众多记忆内容。
        这期间伴随记忆衰退和相关被检索到的记忆的权重强化操作。
        
        Args:
            query_text (str): 要搜索或唤醒的线索文本。
            
        Returns:
            str: 回忆提取到并拼接格式化后的内容结果段落。如果未找到返回相应提示语。
        """
        await self.fade_memory()
        embedding = await self._get_embedding(query_text)
        if not embedding:
            return '获取内容向量失败'
        
        # 通过向量相似度找到最相关的节点，而不是哈希精确匹配
        best_node_id = None
        best_score = -1.0
        for node_id, node_data in self._memory_net.nodes(data=True):
            vec = node_data.get("vector")
            if vec:
                score = await self._calc_cosine(embedding, vec)
                if score > best_score:
                    best_score = score
                    best_node_id = node_id
        
        if best_node_id is None or best_score < 0.4:
            return f'未找到相关记忆'
        
        recall_info = await self.retrieve_memory_net(best_node_id, search_depth=3, min_weight_threshold=0.4)
        if not recall_info:
            return '未找到相关记忆'
        
        # 格式化为 LLM 可读的结构化文本
        result_lines = []
        for i, info in enumerate(recall_info, 1):
            result_lines.append(f"[记忆 #{i}] (记忆强度:{info['weight']:.2f},情绪强度:{info['emotion_intensity']:.2f})\n{info['content']}")
        
        await self.save_memory_graph()
        return '\n\n'.join(result_lines)

memory_instance = Memory()
