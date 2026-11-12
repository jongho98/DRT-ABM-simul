"""Normalize the upstream XLS road inputs and build a small SQLite database."""
from pathlib import Path
import json
import sqlite3
import hashlib
import pandas as pd
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

ROOT = Path(__file__).resolve().parents[1]

def prepare(root=ROOT):
    raw = root / "data/raw"
    out = root / "data/processed"
    out.mkdir(parents=True, exist_ok=True)
    nodes = pd.read_excel(raw / "node.xls", engine="xlrd")
    links = pd.read_excel(raw / "link.xls", engine="xlrd")
    nodes.columns = ["node_id", "x_coord", "y_coord"]
    links.columns = ["link_id", "from_node_id", "to_node_id"]
    nodes["node_id"] = nodes.node_id.astype(int)
    for col in links.columns:
        links[col] = links[col].astype(int)
    if nodes.node_id.duplicated().any() or links.link_id.duplicated().any():
        raise ValueError("Node and link IDs must be unique")
    ids = set(nodes.node_id)
    if not set(links.from_node_id).union(links.to_node_id) <= ids:
        raise ValueError("A link references an absent node")
    index = {node: i for i, node in enumerate(nodes.node_id)}
    a = links.from_node_id.map(index).to_numpy()
    b = links.to_node_id.map(index).to_numpy()
    graph = coo_matrix((np.ones(len(links)), (a,b)), shape=(len(nodes),len(nodes))).tocsr()
    stats = {"nodes": len(nodes), "directed_link_rows": len(links),
             "duplicate_directed_pairs": int(links.duplicated(["from_node_id", "to_node_id"]).sum()),
             "used_by_minimal_manhattan_simulation": False,
             "coordinate_crs": "not documented by upstream; raw values preserved",
             "upstream_commit": "f46db88dcabad541cb08d5fbb0ff95f027c8d2ad"}
    for connection in ["weak", "strong"]:
        count, labels = connected_components(graph, directed=True, connection=connection)
        stats[connection + "_components"] = int(count)
        stats[connection + "_largest_component_nodes"] = int(np.bincount(labels).max())
    for name in ["node.xls", "link.xls"]:
        stats[name + "_sha256"] = hashlib.sha256((raw / name).read_bytes()).hexdigest()
    nodes.to_csv(out / "nodes.csv", index=False)
    links.to_csv(out / "links.csv", index=False)
    db = out / "network.sqlite"
    with sqlite3.connect(db) as con:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("DROP TABLE IF EXISTS links")
        con.execute("DROP TABLE IF EXISTS nodes")
        con.execute("DROP TABLE IF EXISTS metadata")
        con.execute("CREATE TABLE nodes(node_id INTEGER PRIMARY KEY, x_coord REAL NOT NULL, y_coord REAL NOT NULL)")
        con.execute("CREATE TABLE links(link_id INTEGER PRIMARY KEY, from_node_id INTEGER NOT NULL REFERENCES nodes(node_id), to_node_id INTEGER NOT NULL REFERENCES nodes(node_id))")
        con.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.executemany("INSERT INTO nodes VALUES (?,?,?)", nodes.itertuples(index=False, name=None))
        con.executemany("INSERT INTO links VALUES (?,?,?)", links.itertuples(index=False, name=None))
        con.executemany("INSERT INTO metadata VALUES (?,?)", [(k,json.dumps(v,ensure_ascii=False)) for k,v in stats.items()])
        con.execute("CREATE INDEX IF NOT EXISTS links_from_idx ON links(from_node_id)")
        con.execute("CREATE INDEX IF NOT EXISTS links_to_idx ON links(to_node_id)")
    (out / "network_summary.json").write_text(json.dumps(stats, indent=2)+"\n",encoding="utf-8")
    print(json.dumps(stats, indent=2))
    return stats

if __name__ == "__main__":
    prepare()
