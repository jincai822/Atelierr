#!/usr/bin/env python3
"""
开发前自动检查脚本

执行全面的开发前检查，确保：
1. PRD 文档完整且一致
2. 项目结构与开发计划对齐
3. Atelier 和 Atelierr 文件清晰分离
"""

import os
from pathlib import Path
from typing import List, Tuple

# ANSI 颜色
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
RESET = '\033[0m'

# 检查结果
issues = {
    "critical": [],
    "warning": [],
    "info": []
}


def check_file_exists(path: str) -> bool:
    """检查文件是否存在"""
    return Path(path).exists()


def print_section(title: str):
    """打印章节标题"""
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}{title}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")


def print_result(passed: bool, message: str):
    """打印检查结果"""
    if passed:
        print(f"  {GREEN}✅{RESET} {message}")
    else:
        print(f"  {RED}❌{RESET} {message}")


def print_warning(message: str):
    """打印警告"""
    print(f"  {YELLOW}⚠️{RESET}  {message}")


def check_prd_documents():
    """检查 PRD 文档完整性"""
    print_section("1. PRD 文档检查")
    
    # 核心文档
    core_docs = [
        "docs/prd/ARCHITECTURE-LOCKED-V1.md",
        "docs/prd/IMPLEMENTATION-PLAN-PARALLEL.md",
        "docs/PROJECT-STRUCTURE.md",
        "PROJECT-SUMMARY.md",
    ]
    
    print("核心文档:")
    for doc in core_docs:
        exists = check_file_exists(doc)
        print_result(exists, doc)
        if not exists:
            issues["critical"].append(f"缺失核心文档: {doc}")
    
    # 支持文档
    support_docs = [
        "docs/prd/multimodal-input-processing.md",
        "docs/prd/large-file-handling.md",
        "docs/prd/README.md",
        "docs/README.md",
        "docs/DOCUMENTATION-STRUCTURE.md",
    ]
    
    print("\n支持文档:")
    for doc in support_docs:
        exists = check_file_exists(doc)
        print_result(exists, doc)
        if not exists:
            issues["warning"].append(f"缺失支持文档: {doc}")
    
    # 用户文档
    user_docs = [
        "README.md",
        "QUICK-START.md",
    ]
    
    print("\n用户文档:")
    for doc in user_docs:
        exists = check_file_exists(doc)
        print_result(exists, doc)
        if not exists:
            issues["critical"].append(f"缺失用户文档: {doc}")


def check_directory_structure():
    """检查目录结构"""
    print_section("2. 目录结构检查")
    
    # Atelierr 核心目录
    atelierr_dirs = {
        "scripts/memory": ["__init__.py", "core.py", "confidence.py", "decay.py", "search.py", "watcher.py", "scheduler.py"],
        "scripts/web": ["__init__.py", "flatnotes_config.py", "integration.py"],
        "scripts/processors": ["__init__.py", "base.py", "image.py", "video.py", "pdf.py", "audio.py", "wechat.py"],
        "scripts/cli": ["__init__.py", "memory_cli.py", "process_cli.py", "batch_cli.py"],
        "scripts/utils": ["__init__.py", "config.py", "file_utils.py", "text_utils.py", "date_utils.py"],
    }
    
    print("Atelierr 核心目录:")
    for dir_path, expected_files in atelierr_dirs.items():
        dir_exists = Path(dir_path).is_dir()
        print_result(dir_exists, f"{dir_path}/")
        
        if dir_exists:
            for file_name in expected_files:
                file_path = f"{dir_path}/{file_name}"
                file_exists = check_file_exists(file_path)
                if file_exists:
                    print(f"    {GREEN}✓{RESET} {file_name}")
                else:
                    print(f"    {YELLOW}○{RESET} {file_name} (待创建)")
        else:
            issues["critical"].append(f"缺失目录: {dir_path}")
    
    # 配置和部署目录
    other_dirs = [
        "config",
        "docker",
        "tests",
        "examples",
        "tools",
    ]
    
    print("\n其他必需目录:")
    for dir_path in other_dirs:
        dir_exists = Path(dir_path).is_dir()
        print_result(dir_exists, f"{dir_path}/")
        if not dir_exists:
            issues["critical"].append(f"缺失目录: {dir_path}")


def check_atelier_isolation():
    """检查 Atelier 框架文件隔离"""
    print_section("3. Atelier 框架隔离检查")
    
    # 检查 scripts/ 目录中的 Atelier 文件
    scripts_dir = Path("scripts")
    
    if not scripts_dir.exists():
        print_result(False, "scripts/ 目录不存在")
        return
    
    # Atelierr 的目录（应该保留）
    atelierr_dirs = {"memory", "web", "processors", "cli", "utils"}
    
    # 计数 Atelier 文件
    atelier_files = []
    for item in scripts_dir.iterdir():
        if item.is_file() and item.suffix == ".py":
            # 排除 __init__.py
            if item.name != "__init__.py":
                atelier_files.append(item.name)
        elif item.is_dir() and item.name not in atelierr_dirs:
            # 非 Atelierr 的目录
            if item.name not in {"__pycache__", ".pytest_cache"}:
                atelier_files.append(f"{item.name}/")
    
    if atelier_files:
        print_warning(f"发现 {len(atelier_files)} 个 Atelier 框架文件/目录在 scripts/")
        print(f"\n  示例（前 10 个）:")
        for f in atelier_files[:10]:
            print(f"    • scripts/{f}")
        
        if len(atelier_files) > 10:
            print(f"    ... 还有 {len(atelier_files) - 10} 个")
        
        issues["warning"].append(f"scripts/ 目录包含 {len(atelier_files)} 个 Atelier 文件，建议隔离")
        
        print(f"\n  {YELLOW}建议: 移动这些文件到 scripts/atelier/ 子目录{RESET}")
    else:
        print_result(True, "scripts/ 目录已清理，只包含 Atelierr 文件")


def check_config_files():
    """检查配置文件"""
    print_section("4. 配置文件检查")
    
    # Atelierr 配置文件
    atelierr_configs = [
        "requirements.txt",
        ".gitignore",
        "pytest.ini",
    ]
    
    print("Atelierr 配置文件:")
    for config in atelierr_configs:
        exists = check_file_exists(config)
        print_result(exists, config)
        if not exists:
            issues["critical"].append(f"缺失配置文件: {config}")
    
    # Atelier 配置文件（应该保留但标记）
    atelier_configs = [
        ("pyproject.toml", "Atelier 项目配置"),
        ("uv.lock", "Atelier 依赖锁"),
        ("semantic.toml.example", "Atelier 语义搜索"),
    ]
    
    print("\nAtelier 配置文件（保留但不用于 Atelierr）:")
    for config, desc in atelier_configs:
        exists = check_file_exists(config)
        if exists:
            print(f"  {YELLOW}○{RESET} {config} - {desc}")


def check_consistency():
    """检查文档一致性"""
    print_section("5. 文档一致性检查")
    
    # 读取核心架构文档
    arch_file = "docs/prd/ARCHITECTURE-LOCKED-V1.md"
    if check_file_exists(arch_file):
        with open(arch_file, 'r', encoding='utf-8') as f:
            arch_content = f.read()
        
        # 检查关键术语
        terms = {
            "MemoryTree": "记忆树核心类",
            "Confidence": "可信度机制",
            "Flatnotes": "Web 界面",
            "三层记忆": "短期/中期/长期",
        }
        
        print("关键术语检查:")
        for term, desc in terms.items():
            if term in arch_content:
                print_result(True, f"{term} - {desc}")
            else:
                print_result(False, f"{term} 未在架构文档中找到")
                issues["warning"].append(f"架构文档缺失关键术语: {term}")
    else:
        print_result(False, f"核心架构文档不存在: {arch_file}")


def generate_isolation_script():
    """生成隔离脚本"""
    print_section("6. 生成隔离脚本")
    
    script_content = """#!/bin/bash
# Atelier 框架文件隔离脚本

echo "🔧 开始隔离 Atelier 框架文件..."

# 创建 atelier 子目录
mkdir -p scripts/atelier

# 移动 Atelier Python 脚本（保留 Atelierr 目录）
find scripts -maxdepth 1 -type f -name "*.py" ! -name "__init__.py" -exec mv {} scripts/atelier/ \\;

# 移动 Atelier 子目录（保留 Atelierr 目录）
for dir in scripts/*/; do
    dirname=$(basename "$dir")
    if [[ "$dirname" != "memory" && "$dirname" != "web" && "$dirname" != "processors" && "$dirname" != "cli" && "$dirname" != "utils" && "$dirname" != "atelier" ]]; then
        mv "scripts/$dirname" scripts/atelier/
    fi
done

echo "✅ 隔离完成！"
echo ""
echo "Atelier 文件已移动到: scripts/atelier/"
echo "Atelierr 文件保留在: scripts/memory/, scripts/web/, scripts/processors/"
"""
    
    script_path = "tools/isolate_atelier.sh"
    with open(script_path, 'w') as f:
        f.write(script_content)
    
    os.chmod(script_path, 0o755)
    
    print(f"  {GREEN}✅{RESET} 已生成隔离脚本: {script_path}")
    print(f"\n  执行方式: bash {script_path}")


def print_summary():
    """打印检查总结"""
    print_section("检查总结")
    
    total_issues = len(issues["critical"]) + len(issues["warning"]) + len(issues["info"])
    
    if issues["critical"]:
        print(f"{RED}❌ 严重问题 ({len(issues['critical'])}个):{RESET}")
        for issue in issues["critical"]:
            print(f"  • {issue}")
    
    if issues["warning"]:
        print(f"\n{YELLOW}⚠️  警告 ({len(issues['warning'])}个):{RESET}")
        for issue in issues["warning"]:
            print(f"  • {issue}")
    
    if issues["info"]:
        print(f"\n{BLUE}ℹ️  信息 ({len(issues['info'])}个):{RESET}")
        for issue in issues["info"]:
            print(f"  • {issue}")
    
    print(f"\n{'='*60}")
    if issues["critical"]:
        print(f"{RED}❌ 检查未通过 - 请修复严重问题后再开始开发{RESET}")
        return False
    elif issues["warning"]:
        print(f"{YELLOW}⚠️  检查通过但有警告 - 建议处理后再开发{RESET}")
        return True
    else:
        print(f"{GREEN}✅ 检查完全通过 - 可以开始开发！{RESET}")
        return True


def main():
    """主函数"""
    print(f"\n{BLUE}{'='*60}")
    print("  Atelierr 开发前检查")
    print(f"{'='*60}{RESET}\n")
    
    # 执行各项检查
    check_prd_documents()
    check_directory_structure()
    check_atelier_isolation()
    check_config_files()
    check_consistency()
    generate_isolation_script()
    
    # 打印总结
    passed = print_summary()
    
    # 返回状态码
    return 0 if passed else 1


if __name__ == "__main__":
    exit(main())
