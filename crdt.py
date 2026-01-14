# crdt.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple

CrdtId = Tuple[int, str]

HEAD: CrdtId = (0, "HEAD")


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
        # Sort descending so newer nodes (higher counter) come first (left)
        self.children[after].sort(reverse=True)

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

    def state_hash(self) -> int:
        """Compute a hash of the visible text state."""
        return hash(self.render())

    def to_dict(self) -> dict:
        """Serialize CRDT state to a JSON-compatible dict."""
        nodes_list = []
        for node in self.nodes.values():
            nodes_list.append({
                "id": list(node.id),
                "after": list(node.after),
                "text": node.text,
                "deleted": node.deleted
            })
        return {"nodes": nodes_list}

    @classmethod
    def from_dict(cls, data: dict) -> "RgaCrdt":
        """Deserialize CRDT state from a dict."""
        crdt = cls()
        crdt.nodes = {}
        crdt.children = {}

        for node_data in data.get("nodes", []):
            node_id = tuple(node_data["id"])
            after_id = tuple(node_data["after"])
            node = Node(
                id=node_id,
                after=after_id,
                text=node_data["text"],
                deleted=node_data["deleted"]
            )
            crdt.nodes[node_id] = node
            # Don't add self-referencing nodes to children (HEAD points to itself)
            if node_id != after_id:
                crdt.children.setdefault(after_id, []).append(node_id)
            crdt.children.setdefault(node_id, [])

        # Sort children for deterministic ordering (descending for RGA)
        for children_list in crdt.children.values():
            children_list.sort(reverse=True)

        return crdt
