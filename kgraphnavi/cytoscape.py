#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      cytoscape.py
"""

from .misc import hash_color

GRAPHjs1 = """
      var cy = cytoscape({
        container: document.getElementById('cy'),
"""

def get_all_nodes(edges):
    nodes = set()
    for node1, node2 in edges:
        nodes.add(node1)
        nodes.add(node2)
    return nodes

def make_node_style(class_name=None, shape='circle', color='aqua', label='data(id)'):
    if class_name:
        return f"{{ selector: '.{class_name}', style: {{ shape: '{shape}', 'background-color': '{color}', label: '{label}' }} }}"
    return f"{{ selector: 'node', style: {{ shape: '{shape}', 'background-color': '{color}', label: '{label}' }} }}"

def make_edge_style(edge_styles):
    return f"{{ selector: 'edge', style: {{ 'target-arrow-shape': '{edge_styles}', 'curve-style': 'bezier'}} }}"

def make_graphjs(graphjs_filename, edges, nodes=None, edge_styles=None):
    """nodesはclass名をキーにnode_idのリストを値とするdict。
       nodesが指定されていないときは、edgesからnodesを作成する
    """
    if nodes is None:
        nodes = get_all_nodes(edges)
        key0 = 'class0'
        classes = {key0: nodes}
        node_str_list = [f"{{ data: {{ id: '{node_id}' }}, classes: '{key0}' }}" for node_id in classes[key0]]
    else:
        node_str_list = []
        classes = nodes.keys()
        for key in classes:
            node_str_list.extend([f"{{ data: {{ id: '{node_id}' }}, classes: '{key}' }}" for node_id in nodes[key]])
    nodes = ',\n'.join(node_str_list)
    nodes_str = f'nodes: [\n{nodes}\n]'
    edge_str_list = []
    for node1, node2 in edges:
        edgename = node1 + node2
        edge_str_list.append(f"{{ data: {{ id: '{edgename}', source: '{node1}', target: '{node2}'}} }}")
    edges = ',\n'.join(edge_str_list)
    edges_str = f'edges: [\n{edges}\n]'
    elements = "elements: {\n" + nodes_str + ',\n' + edges_str + "},"
    node_class_style = make_node_style()
    if edge_styles:
        edge_style_json = make_edge_style(edge_styles)
        node_class_style += ', ' + edge_style_json
    colors = ['green', 'aqua', 'violet', 'red']
    for class_name in classes:
        node_class_style += "," + make_node_style(class_name, shape = 'circle', color = f'#{hash_color(class_name)}')
    style = f"style: [ {node_class_style} ]"
    data = GRAPHjs1 + elements + style + "});"
    with open(f'templates/{graphjs_filename}', 'w') as wf:
        wf.write(data)
