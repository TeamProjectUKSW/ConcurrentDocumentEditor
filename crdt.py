# crdt.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple

CrdtId = Tuple[str, int]

HEAD: CrdtId = ("HEAD", 0)


@dataclass
class Node:

    id: CrdtId
    after: CrdtId
    text: str
    deleted: bool = False


class RgaCrdt:


    def __init__(self):
        self.nodes: Dict[CrdtId, Node] = {HEAD: Node(id=HEAD, after=HEAD, text="", deleted=False)}
        self.children: Dict[CrdtId, List[CrdtId]] = {HEAD: []} 

    def has(self, node_id: CrdtId) -> bool:
        return node_id in self.nodes

    def apply_insert(self, after: CrdtId, node_id: CrdtId, text: str) -> bool:

        if after not in self.nodes:
            return False  

        if node_id in self.nodes:
            return True  

        self.nodes[node_id] = Node(id=node_id, after=after, text=text, deleted=False)

        self.children.setdefault(after, []).append(node_id)
        self.children[after].sort()

        self.children.setdefault(node_id, [])
        return True

    def apply_delete(self, node_id: CrdtId) -> bool:

        if node_id not in self.nodes:
            return False
        if node_id == HEAD:
            return True

        self.nodes[node_id].deleted = True
        return True

    def _visible_nodes_in_order(self) -> List[Node]:

        out: List[Node] = []

        def dfs(parent: CrdtId):
            for cid in self.children.get(parent, []):
                n = self.nodes[cid]
                if not n.deleted:
                    out.append(n)
                dfs(cid)

        dfs(HEAD)
        return out

    def render(self) -> str:

        return "".join(n.text for n in self._visible_nodes_in_order())

    def visible_id_map(self) -> List[CrdtId]:

        mapping: List[CrdtId] = []
        for n in self._visible_nodes_in_order():
            for _ in n.text:
                mapping.append(n.id)
        return mapping
