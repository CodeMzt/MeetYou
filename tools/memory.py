import hashlib
import aiohttp
import os
import json
import networkx as nx
import numpy as np
from core.config_manage import ConfigManager
from core.sensors import system_output
        
__memory_file_path = "memory.json"
__embedding_model = ''
__embedding_api_key = ''
__embedding_api_url = ''

__memory_net = None

def __generate_node_id(text_content):
    # 使用 SHA-256 哈希函数
    hash_obj = hashlib.sha256(text_content.encode('utf-8'))
    # 取前 16 个字符作为节点 ID
    return hash_obj.hexdigest()[:16]
    
async def __get_embedding(text: str, api_key: str, api_url: str, model: str):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "input": text
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload) as resp:
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
        system_output(f"[tool] [memory] [Error]: 获取记忆向量失败: {e}")
        return []

async def __calc_cosine(embedding1: list, embedding2: list):
    norm1 = np.linalg.norm(embedding1)
    norm2 = np.linalg.norm(embedding2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return np.dot(embedding1, embedding2) / (norm1 * norm2)

async def fade_memory():
    global __memory_net
    id_to_fade = []
    for node_id, node_data in __memory_net.nodes(data=True):
        current_weight = node_data.get("memory_weight", 0.0)
        __memory_net.nodes[node_id]["memory_weight"] = current_weight * 0.95
        if(current_weight <= 0.2):
            id_to_fade.append(node_id)

    for node_id in id_to_fade:
        __memory_net.remove_node(node_id)

async def retrieve_memory_net(target_node_id, search_depth=3, min_weight_threshold=0.5):
    global __memory_net
    if not __memory_net.has_node(target_node_id):
        return []
    # 向外扩散 search_depth 步的子图
    sub_graph = nx.ego_graph(__memory_net, target_node_id, radius=search_depth)
    
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
            __memory_net.nodes[node_id]["memory_weight"] += 10 * emotion_intensity / (1+current_weight)
            
    return extracted_info

async def save_memory_graph():
    graph_data = nx.node_link_data(__memory_net, edges = 'edges')
    with open(__memory_file_path, "w",encoding="utf-8") as f:
        json.dump(graph_data, f, ensure_ascii=False)

async def build_synapses():
    global __memory_net
    
    all_nodes = list(__memory_net.nodes(data=True))
    
    # 双重循环比对 (O(N^2) 复杂度，必须在睡觉时做)
    for i in range(len(all_nodes)):
        for j in range(i + 1, len(all_nodes)):
            node_i_id, data_i = all_nodes[i]
            node_j_id, data_j = all_nodes[j]
            
            sim_score = await __calc_cosine(data_i["vector"], data_j["vector"])
            
            if sim_score > 0.80:
                pass
            if sim_score > 0.5:
                # add_edge 会在这两个节点间连线，我们把相似度作为这条线的权重
                __memory_net.add_edge(node_i_id, node_j_id, sim_weight=sim_score)
                system_output(f"[tool] [memory] [Info] [神经突触]: 节点 {node_i_id} 与 {node_j_id} 建立关联 (相似度: {sim_score:.2f})")

async def rebuild_synapses(new_id: str):
    global __memory_net
    all_nodes = list(__memory_net.nodes(data=True))

    for i in range(len(all_nodes)):
        node_i_id, data_i = all_nodes[i]
        sim_score = await __calc_cosine(data_i["vector"], __memory_net.nodes[new_id]["vector"])
        if sim_score > 0.7:
            __memory_net.add_edge(node_i_id, new_id, sim_weight=sim_score)
            system_output(f"[tool] [memory] [Info] [神经突触]: 节点 {node_i_id} 与 {new_id} 建立关联 (相似度: {sim_score:.2f})")

async def init_memory():
    global __memory_file_path, __embedding_model, __embedding_api_key, __embedding_api_url
    config_manager = ConfigManager()
    __memory_file_path = config_manager.get_config_item("memory_file_path")
    __embedding_model = config_manager.get_config_item("embedding_model")
    __embedding_api_key = config_manager.get_config_item("embedding_api_key")
    __embedding_api_url = config_manager.get_config_item("embedding_api_url")
    
    global __memory_net
    __memory_net = nx.Graph()
    graph_data = None
    if os.path.exists(__memory_file_path):
        with open(__memory_file_path, "r",encoding="utf-8") as f:
            content = f.read()
            if content != "":
                graph_data = json.loads(content)

    if graph_data:
        __memory_net = nx.node_link_graph(graph_data, edges = 'edges')

    await build_synapses()
    await fade_memory()

async def save_memory(text: str, text_emotion_intensity: float = 1.0):
    embedding = await __get_embedding(text, __embedding_api_key, __embedding_api_url, __embedding_model)
    if not embedding:
        return '获取内容向量失败'
    
    global __memory_net
    node_id = __generate_node_id(text)
    if node_id in __memory_net.nodes:
        return f'记忆已存在,id={node_id}'
    initial_weight = 0.5 + text_emotion_intensity * 0.5
    __memory_net.add_node(
        node_id,
        content=text,
        vector=embedding,
        memory_weight=initial_weight,
        emotion_intensity=text_emotion_intensity
    )
    await rebuild_synapses(node_id)
    await save_memory_graph()
    return f'成功保存记忆,id={node_id}'

async def update_memory(nodeid: str, text: str):
    embedding = await __get_embedding(text, __embedding_api_key, __embedding_api_url, __embedding_model)
    if not embedding:
        return '获取内容向量失败'
    
    global __memory_net
    if nodeid not in __memory_net.nodes:
        __memory_net.add_node(nodeid, content=text, vector=embedding, memory_weight=10, emotion_intensity=0.5)
    else:
        __memory_net.nodes[nodeid]["content"] = text
        __memory_net.nodes[nodeid]["vector"] = embedding
    await save_memory_graph()
    return f'成功更新记忆,id={nodeid}'

async def recall_memory(text: str):
    await fade_memory()
    embedding = await __get_embedding(text, __embedding_api_key, __embedding_api_url, __embedding_model)
    if not embedding:
        return '获取内容向量失败'
    
    global __memory_net
    # 通过向量相似度找到最相关的节点，而不是哈希精确匹配
    best_node_id = None
    best_score = -1.0
    for node_id, node_data in __memory_net.nodes(data=True):
        vec = node_data.get("vector")
        if vec:
            score = await __calc_cosine(embedding, vec)
            if score > best_score:
                best_score = score
                best_node_id = node_id
    
    if best_node_id is None or best_score < 0.4:
        return f'未找到相关记忆'
    
    recall_info = await retrieve_memory_net(best_node_id, search_depth=3, min_weight_threshold=0.4)
    if not recall_info:
        return '未找到相关记忆'
    
    # 格式化为 LLM 可读的结构化文本
    result_lines = []
    for i, info in enumerate(recall_info, 1):
        result_lines.append(f"[记忆 #{i}] (记忆强度:{info['weight']:.2f},情绪强度:{info['emotion_intensity']:.2f})\n{info['content']}")
    
    await save_memory_graph()
    return '\n\n'.join(result_lines)
