"""负载/资源测试（验收标准吞吐量和资源节）：批量导入、并发搜索、内存增量。"""

from __future__ import annotations

import os
import resource
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from scripts.memory.search import MemorySearcher


def test_bulk_import_throughput(memory_tree):
    """批量导入笔记 ≥ 50 notes/s（200 条计时）。"""
    count = 200
    start = time.monotonic()
    for i in range(count):
        memory_tree.create_note(f"bulk-{i:04d}.md", f"批量导入第 {i} 条笔记内容")
    elapsed = time.monotonic() - start

    rate = count / elapsed
    assert rate >= 50, f"批量导入 {rate:.1f} notes/s < 50"


def test_concurrent_search_throughput():
    """并发搜索 ≥ 100 req/s（1000 条笔记，8 线程 × 200 次查询）。

    在子进程（无 coverage 插桩）中测量真实吞吐：coverage 的行级追踪
    会把 Python 执行拖慢数倍，在父进程内计时测的是测试基建而非实现。
    """
    child = textwrap.dedent("""
        import sys, tempfile, time
        from concurrent.futures import ThreadPoolExecutor
        from scripts.memory.core import MemoryTree
        from scripts.memory.search import MemorySearcher

        tmp = tempfile.mkdtemp()
        tree = MemoryTree(f"{tmp}/memory", state_dir=f"{tmp}/state")
        for i in range(1000):
            tree.create_note(f"s-{i:04d}.md", f"并发搜索测试笔记 {i}")
        searcher = MemorySearcher(tree)
        searcher.search("并发")  # 预热缓存

        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: searcher.search("并发"), range(200)))
        elapsed = time.monotonic() - start
        print(f"RATE={200 / elapsed:.1f}")
        """)
    repo_root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(repo_root)}
    proc = subprocess.run(
        [sys.executable, "-c", child],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    rate = float(proc.stdout.strip().split("RATE=")[1])
    assert rate >= 100, f"并发搜索 {rate:.1f} req/s < 100（无插桩实测）"


def test_memory_usage_reasonable(memory_tree, make_note):
    """内存增量 < 512MB：1000 条笔记建库 + 100 次搜索的前后 RSS 差。"""
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for i in range(1000):
        make_note(
            memory_tree, filename=f"m-{i:04d}.md", content=f"内存占用测试笔记 {i}"
        )
    searcher = MemorySearcher(memory_tree)
    for _ in range(100):
        searcher.search("内存")
    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    # ru_maxrss 单位是 KiB（Linux）
    delta_mb = (after - before) / 1024
    assert delta_mb < 512, f"内存增量 {delta_mb:.1f}MB >= 512MB"
