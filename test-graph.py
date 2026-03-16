
import json
import networkx as nx
import hashlib
import random

# 1. 声明一张无向图 (因为如果 A 像 B，那么 B 也像 A，双向联想)
_memory_net = None

def _calc_cosine_similarity(vec1: list, vec2: list):
    """
    计算两个向量的余弦相似度
    """
    
    # 计算点积
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    
    # 计算每个向量的范数 (长度)
    norm_vec1 = sum(a * a for a in vec1) ** 0.5
    norm_vec2 = sum(b * b for b in vec2) ** 0.5
    
    # 避免除以零
    if norm_vec1 == 0 or norm_vec2 == 0:
        return 0.0
    
    # 计算余弦相似度
    return dot_product / (norm_vec1 * norm_vec2)

def add_new_memory_node(node_id, text_content, vector_data):
    """
    局部教学代码：向图谱中打入一个新的记忆节点
    """
    global _memory_net
    
    # 刚存入的记忆，默认初始权重给 1.0
    initial_weight = 1.0
    
    # add_node 的第一个参数是唯一的序号 (就像单片机的设备 ID)
    # 后面的 kwargs 关键字参数，就是你想挂载的所有属性
    _memory_net.add_node(
        node_id,
        content=text_content,
        vector=vector_data,
        memory_weight=initial_weight
    )
    print(f"[底层操作]: 记忆节点 {node_id} 已烧录。")



def retrieve_memory_network(target_node_id, search_depth=1, min_weight_threshold=0.5):
    """
    局部教学代码：按指定深度和权重阈值，提取记忆子图
    """
    global _memory_net
    
    # 如果节点不存在，直接短路返回
    if not _memory_net.has_node(target_node_id):
        return []
        
    # 核心魔法：直接提取以 target_node_id 为中心，向外扩散 search_depth 步的子图
    sub_graph = nx.ego_graph(_memory_net, target_node_id, radius=search_depth)
    
    extracted_contexts = []
    
    # 遍历这个被抠出来的局部网络
    for node_id, node_data in sub_graph.nodes(data=True):
        current_weight = node_data.get("memory_weight", 0.0)
        
        # 触发你的阈值截断机制：如果这条记忆太久没用（权重过低），则不向大模型提供
        if current_weight >= min_weight_threshold:
            extracted_contexts.append(node_data.get("content"))
            
            # 可选的高级操作：每次被成功回忆起，强化它的记忆权重 (模拟突触强化)
            _memory_net.nodes[node_id]["memory_weight"] += 0.1
            
    return extracted_contexts

def _generate_node_id(text_content):
    """
    生成一个基于文本内容的唯一节点 ID
    """
    # 使用 SHA-256 哈希函数
    hash_obj = hashlib.sha256(text_content.encode('utf-8'))
    # 取前 8 个字符作为节点 ID
    return hash_obj.hexdigest()[:8]

from pyvis.network import Network
import networkx as nx

def export_memory_graph_html(html_file_name="memory_graph_view.html"):
    """
    局部教学代码：极致性能版可视化（砍掉所有前端物理计算与曲线特效）
    """
    global _memory_net
    
    if _memory_net.number_of_nodes() == 0:
        print("[可视化]: 当前记忆库为空，无需渲染。")
        return

    # 1. 极简画布设置
    interactive_net = Network(
        height="1000px", 
        width="100%", 
        bgcolor="#1e1e1e", 
        font_color="white",
        select_menu=True
    )
    
    # 2. 【核心大招】：在 Python 端直接算好坐标，前端纯静态展示！
    # 使用 NetworkX 的 Kamada-Kawai 算法或 Spring 算法在后台瞬间算出 (X, Y)
    pos = nx.spring_layout(_memory_net, seed=42) 
    
    # 3. 手动将节点和预计算的坐标压入前端画布
    for node_id, node_data in _memory_net.nodes(data=True):
        mem_content = node_data.get("content", "空内容")
        mem_weight = node_data.get("memory_weight", 1.0)
        
        # 取出预计算的坐标 (pyvis 画布较大，需要乘以 1000 放大间距)
        x_pos = pos[node_id][0] * 1000
        y_pos = pos[node_id][1] * 1000
        
        interactive_net.add_node(
            node_id,
            label=str(node_id)[:8] + "...",
            title=f"【权重】: {mem_weight:.2f}\n【记忆】: {mem_content}",
            value=mem_weight,
            x=x_pos,      # 强行指定物理 X 坐标
            y=y_pos,      # 强行指定物理 Y 坐标
            physics=False # 彻底杀死这个节点的物理引擎！
        )
        
    # 4. 手动压入边（去除极其耗费性能的曲线平滑特效，改用最快的直线）
    for source, target, edge_data in _memory_net.edges(data=True):
        sim_weight = edge_data.get("sim_weight", 0.0)
        interactive_net.add_edge(
            source, 
            target, 
            value=sim_weight,
            title=f"相似度: {sim_weight:.2f}",
            smooth=False  # 砍掉曲线特效，画纯直线
        )
        
    # 5. 全局彻底关闭物理引擎
    interactive_net.toggle_physics(False)
    
    interactive_net.save_graph(html_file_name)
    print(f"\n[可视化探针]: 极致静态版图谱已生成。前端零计算，秒开！")

import os

if __name__ == "__main__":
    # 初始化记忆网络
    _memory_net = nx.Graph()
    graph_data = None
    if os.path.exists("memory_graph.json"):
        with open("memory_graph.json", "r",encoding="utf-8") as f:
            content = f.read()
            if content != "":
                graph_data = json.loads(content)

    if graph_data:
        _memory_net = nx.node_link_graph(graph_data, edges = 'edges')

    # for i in range(100):
    #     test_content = f"test_memory_{i}_{random.randint(0, 10**9)}"
    #     node_id = _generate_node_id(test_content)
    #     vector = [random.random() for _ in range(3)]
    #     add_new_memory_node(node_id, test_content, vector)
    #     print(f"为内容 '{test_content}' 生成的节点 ID 是: {node_id}")
    while True:
        test_content = input("请输入测试记忆id: ")
        if(test_content == ""):
            break
        retrieved_contexts = retrieve_memory_network(test_content,4,0.8)
        print(retrieved_contexts)
    sleep_task_build_synapses()
    export_memory_graph_html()
    graph_data = nx.node_link_data(_memory_net, edges = 'edges')
    with open("memory_graph.json", "w",encoding="utf-8") as f:
        json.dump(graph_data, f, ensure_ascii=False)
    input("按任意键继续...")
