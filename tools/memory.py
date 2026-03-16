import hashlib
import aiohttp
import os
import json
from core.config_manage import ConfigManager
        
__deep_memory_file_path = "deep_memory.json"
__embedding_model = ''
__embedding_api_key = ''
__embedding_api_url = ''

_memory_net = None

async def __generate_node_id(text_content):
    # 使用 SHA-256 哈希函数
    hash_obj = hashlib.sha256(text_content.encode('utf-8'))
    # 取前 8 个字符作为节点 ID
    return hash_obj.hexdigest()[:8]
    
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
        print(f"获取记忆向量失败: {e}")
        return []

async def __calc_cosine(embedding1: list, embedding2: list):
    dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
    norm1 = sum(a ** 2 for a in embedding1) ** 0.5
    norm2 = sum(b ** 2 for b in embedding2) ** 0.5
    if norm1 == 0 or norm2 == 0:
        return 0
    return dot_product / (norm1 * norm2)

async def sleep_task_build_synapses():
    global _memory_net
    
    all_nodes = list(_memory_net.nodes(data=True))
    
    # 双重循环比对 (O(N^2) 复杂度，这就是为什么必须在睡觉时做)
    for i in range(len(all_nodes)):
        for j in range(i + 1, len(all_nodes)):
            node_i_id, data_i = all_nodes[i]
            node_j_id, data_j = all_nodes[j]
            
            # 计算两者的向量内积/相似度
            sim_score = await __calc_cosine(data_i["vector"], data_j["vector"])
            
            # 你的核心机制：如果相似度大于 0.6，建立连接索引
            if sim_score > 0.9:
                # add_edge 会在这两个节点间连线，我们把相似度作为这条线的权重
                _memory_net.add_edge(node_i_id, node_j_id, sim_weight=sim_score)
                print(f"[神经突触]: 节点 {node_i_id} 与 {node_j_id} 建立关联 (相似度: {sim_score:.2f})")
        
async def init_deep_memory():
    global __deep_memory_file_path, __embedding_model, __embedding_api_key, __embedding_api_url
    config_manager = ConfigManager()
    __deep_memory_file_path = config_manager.get_config_item("deep_memory_file_path")
    __embedding_model = config_manager.get_config_item("embedding_model")
    __embedding_api_key = config_manager.get_config_item("embedding_api_key")
    __embedding_api_url = config_manager.get_config_item("embedding_api_url")

async def save_deep_memory(text: str):
    embedding = await __get_embedding(text, __embedding_api_key, __embedding_api_url, __embedding_model)
    if not embedding:
        return 'False'
    db_list = []
    if os.path.exists(__deep_memory_file_path):
        with open(__deep_memory_file_path, "r",encoding="utf-8") as f:
            try:
                content = f.read()
                if content:
                    db_list = json.loads(content)
            except Exception as e:
                return (f"读取记忆文件失败: {e}")
    else:
        dir_path = os.path.dirname(__deep_memory_file_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
    db_list.append({
        "text": text,
        "embedding": embedding
    })
    try:
        with open(__deep_memory_file_path, "w",encoding="utf-8") as f:
            json.dump(db_list, f, ensure_ascii=False)
    except Exception as e:
        return (f"写入记忆文件失败: {e}")
    return 'True'

async def recall_deep_memory(text: str):
    if not os.path.exists(__deep_memory_file_path):
        return '记忆文件不存在'
    embedding = await __get_embedding(text, __embedding_api_key, __embedding_api_url, __embedding_model)
    if not embedding:
        return '获取记忆向量失败'
    max_cosine = -1
    max_text = ''
    with open(__deep_memory_file_path, "r",encoding="utf-8") as f:
        try:
            content = f.read()
            if content:
                db_list = json.loads(content)
            else:
                return '记忆文件为空'
        except Exception as e:
            return (f"读取记忆文件失败: {e}")
        for item in db_list:
            cosine = await __calc_cosine(embedding, item["embedding"])
            if cosine > max_cosine:
                max_cosine = cosine
                max_text = item["text"]
    
    if max_cosine < 0.5:
        return '没有相关记忆'
    return f'相关记忆：{max_text}'
