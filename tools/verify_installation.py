#!/usr/bin/env python3
"""
验证 Atelierr 安装

检查所有依赖和配置是否正确。
"""

import sys
import subprocess
from pathlib import Path


# ANSI 颜色
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
RESET = '\033[0m'


def print_section(title: str):
    """打印章节标题"""
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}  {title}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")


def check_python_version():
    """检查 Python 版本"""
    print("🔍 检查 Python 版本...")
    
    version = sys.version_info
    if version >= (3, 8):
        print(f"  {GREEN}✅{RESET} Python {version.major}.{version.minor}.{version.micro}")
        return True
    else:
        print(f"  {RED}❌{RESET} Python 版本过低: {version.major}.{version.minor}")
        print(f"     需要 Python 3.8+")
        return False


def check_dependencies():
    """检查依赖包"""
    print("🔍 检查依赖包...")
    
    required = {
        "yaml": "pyyaml",
        "watchdog": "watchdog",
        "pytest": "pytest",
    }
    
    all_ok = True
    for import_name, package_name in required.items():
        try:
            __import__(import_name)
            print(f"  {GREEN}✅{RESET} {package_name}")
        except ImportError:
            print(f"  {RED}❌{RESET} {package_name} 未安装")
            print(f"     安装: pip install {package_name}")
            all_ok = False
    
    return all_ok


def check_directories():
    """检查目录结构"""
    print("🔍 检查目录结构...")
    
    required_dirs = [
        "scripts/memory",
        "scripts/web",
        "scripts/processors",
        "scripts/cli",
        "scripts/utils",
        "config",
        "docker",
        "tests",
        "examples",
        "tools",
    ]
    
    all_ok = True
    for dir_path in required_dirs:
        path = Path(dir_path)
        if path.exists():
            print(f"  {GREEN}✅{RESET} {dir_path}")
        else:
            print(f"  {RED}❌{RESET} {dir_path} 不存在")
            all_ok = False
    
    return all_ok


def check_config_files():
    """检查配置文件"""
    print("🔍 检查配置文件...")
    
    required_files = [
        "requirements.txt",
        ".gitignore",
        "pytest.ini",
        "docker/docker-compose.yml",
    ]
    
    all_ok = True
    for file_path in required_files:
        path = Path(file_path)
        if path.exists():
            print(f"  {GREEN}✅{RESET} {file_path}")
        else:
            print(f"  {YELLOW}⚠️{RESET}  {file_path} 不存在")
            all_ok = False
    
    return all_ok


def check_docker():
    """检查 Docker"""
    print("🔍 检查 Docker...")
    
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            print(f"  {GREEN}✅{RESET} {version}")
            return True
        else:
            print(f"  {YELLOW}⚠️{RESET}  Docker 未正确配置")
            return False
    except FileNotFoundError:
        print(f"  {YELLOW}⚠️{RESET}  Docker 未安装（可选，用于 Web 界面）")
        return False
    except subprocess.TimeoutExpired:
        print(f"  {YELLOW}⚠️{RESET}  Docker 命令超时")
        return False


def check_atelierr_modules():
    """检查 Atelierr 模块"""
    print("🔍 检查 Atelierr 模块...")
    
    modules = [
        ("scripts.memory.core", "记忆模块核心"),
        ("scripts.memory.confidence", "Confidence 计算"),
        ("scripts.memory.decay", "自动衰减"),
        ("scripts.memory.search", "搜索功能"),
        ("scripts.web.integration", "Web 集成"),
        ("scripts.processors.base", "处理器基类"),
        ("scripts.processors.image", "图片处理器"),
        ("scripts.processors.pdf", "PDF 处理器"),
        ("scripts.cli.memory_cli", "Memory CLI"),
        ("scripts.utils.config", "配置工具"),
    ]
    
    all_ok = True
    for module_path, description in modules:
        try:
            __import__(module_path)
            print(f"  {GREEN}✅{RESET} {description}")
        except ImportError as e:
            print(f"  {RED}❌{RESET} {description} - 导入失败")
            print(f"     {str(e)}")
            all_ok = False
        except Exception as e:
            print(f"  {YELLOW}⚠️{RESET}  {description} - 有语法错误")
            print(f"     {str(e)}")
            all_ok = False
    
    return all_ok


def generate_report(checks: dict):
    """生成检查报告"""
    print_section("检查报告")
    
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    failed = total - passed
    
    print("检查结果:")
    for check_name, status in checks.items():
        if status:
            print(f"  {GREEN}✅{RESET} {check_name}")
        else:
            print(f"  {RED}❌{RESET} {check_name}")
    
    print(f"\n总计: {total} 项检查")
    print(f"通过: {passed} 项")
    print(f"失败: {failed} 项")
    
    if passed == total:
        print(f"\n{GREEN}✅ 安装验证完全通过！系统准备就绪。{RESET}")
        return True
    elif passed >= total - 1:
        print(f"\n{YELLOW}⚠️  安装基本完成，但有 {failed} 项检查未通过。{RESET}")
        print("   建议修复后再开发，但可以继续。")
        return True
    else:
        print(f"\n{RED}❌ 安装验证失败，请修复 {failed} 项问题。{RESET}")
        return False


def main():
    """运行所有检查"""
    print_section("Atelierr 安装验证")
    
    # 运行所有检查
    checks = {
        "Python 版本": check_python_version(),
        "依赖包": check_dependencies(),
        "目录结构": check_directories(),
        "配置文件": check_config_files(),
        "Docker": check_docker(),
        "Atelierr 模块": check_atelierr_modules(),
    }
    
    # 生成报告
    success = generate_report(checks)
    
    # 返回状态码
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
