#!/usr/bin/env python3
"""
快速初始化 Atelierr 项目结构

用法:
    python tools/init_project.py
"""

from pathlib import Path

# 项目目录结构
STRUCTURE = {
    "scripts": {
        "memory": [
            "__init__.py",
            "core.py",
            "confidence.py",
            "decay.py",
            "search.py",
            "watcher.py",
            "scheduler.py",
        ],
        "web": ["__init__.py", "integration.py"],
        "processors": [
            "base.py",
            "image.py",
            "video.py",
            "pdf.py",
            "audio.py",
            "wechat.py",
        ],
        "cli": ["__init__.py", "memory_cli.py", "process_cli.py", "batch_cli.py"],
        "utils": [
            "__init__.py",
            "file_utils.py",
            "text_utils.py",
            "date_utils.py",
            "config.py",
        ],
    },
    "config": [
        "memory.yaml.example",
        "storage.yaml.example",
        "processors.yaml.example",
        "logging.yaml.example",
    ],
    "docker": [
        "docker-compose.yml",
        ".env.example",
    ],
    "tests": {
        "unit": {
            "test_memory": [
                "__init__.py",
                "test_confidence.py",
                "test_decay.py",
                "test_search.py",
            ],
            "test_processors": [
                "__init__.py",
                "test_image.py",
                "test_video.py",
                "test_pdf.py",
            ],
            "test_utils": ["__init__.py", "test_config.py"],
        },
        "integration": ["__init__.py", "test_memory_web.py", "test_end_to_end.py"],
        "fixtures": ["sample.md", ".gitkeep"],
    },
    "examples": ["basic_usage.py", "batch_processing.py", "custom_processor.py"],
    "tools": ["init_memory.py", "verify_installation.py", "generate_test_data.py"],
}


def create_file(path: Path, content: str = ""):
    """创建文件并写入内容"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(content)
        print(f"  ✅ 创建: {path}")
    else:
        print(f"  ⏭️  跳过: {path} (已存在)")


def create_directory(path: Path):
    """创建目录"""
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        print(f"  📁 创建目录: {path}")


def process_structure(base_path: Path, structure, indent: int = 0):
    """递归处理目录结构"""
    if isinstance(structure, dict):
        for name, content in structure.items():
            current_path = base_path / name
            create_directory(current_path)
            process_structure(current_path, content, indent + 1)
    elif isinstance(structure, list):
        for item in structure:
            file_path = base_path / item
            if item == "__init__.py":
                # 创建空的 __init__.py
                create_file(file_path, '"""TODO: Add module docstring"""\n')
            elif item.endswith(".example"):
                # 创建示例配置文件
                create_file(file_path, f"# {item} - TODO: Add configuration\n")
            elif item == ".gitkeep":
                # 创建 .gitkeep
                create_file(file_path, "")
            else:
                # 创建空文件
                create_file(file_path, f"# TODO: Implement {item}\n")


def create_root_files():
    """创建根目录必要文件"""
    print("\n📝 创建根目录文件...")

    # requirements.txt
    requirements = """# Atelierr 依赖包
# 核心依赖（必需）
pyyaml>=6.0
watchdog>=2.1.0

# OCR（图片处理）
paddleocr>=2.6.0
pillow>=9.0.0

# 视频处理
openai-whisper>=20230314
ffmpeg-python>=0.2.0

# PDF 处理
PyMuPDF>=1.21.0

# CLI 工具
click>=8.0.0
rich>=12.0.0
tqdm>=4.65.0

# 测试
pytest>=7.0.0
pytest-cov>=3.0.0
pytest-mock>=3.10.0

# 开发工具
black>=23.0.0
flake8>=6.0.0
mypy>=1.0.0
"""
    create_file(Path("requirements.txt"), requirements)

    # .gitignore
    gitignore = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual Environment
.venv/
venv/
ENV/
env/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# Testing
.pytest_cache/
.coverage
htmlcov/

# Configs
config/*.yaml
!config/*.yaml.example

# Data
data/
*.db
*.sqlite

# Logs
*.log
logs/

# OS
.DS_Store
Thumbs.db
"""
    create_file(Path(".gitignore"), gitignore)

    # pytest.ini
    pytest_ini = """[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    -v
    --strict-markers
    --cov=scripts
    --cov-report=html
    --cov-report=term-missing
"""
    create_file(Path("pytest.ini"), pytest_ini)


def main():
    """主函数"""
    print("🚀 开始初始化 Atelierr 项目结构...\n")

    base_path = Path(".")

    # 创建目录结构
    print("📁 创建目录结构...")
    process_structure(base_path, STRUCTURE)

    # 创建根目录文件
    create_root_files()

    # 总结
    print("\n" + "=" * 60)
    print("✅ 项目结构初始化完成！")
    print("=" * 60)
    print("\n📋 下一步:")
    print("  1. 安装依赖:")
    print("     python3 -m venv .venv")
    print("     source .venv/bin/activate")
    print("     pip install -r requirements.txt")
    print()
    print("  2. 复制配置文件:")
    print("     cp config/memory.yaml.example config/memory.yaml")
    print()
    print("  3. 开始开发:")
    print("     code scripts/memory/core.py")
    print()
    print("  4. 运行测试:")
    print("     pytest")
    print()


if __name__ == "__main__":
    main()
