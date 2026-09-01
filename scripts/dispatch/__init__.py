"""通道→处理器自动分发（dispatch）。

独立顶层组合模块：memory/ 与 processors/ 互不 import，本包是两者之间
唯一的接线点。当前实现：links（抖音链接自动抓取转写，见 links.py）、
todos（行动意图抽取，见 todos.py）、media（attachments/ 截图录音自动
OCR/转写，见 media.py）、digest（晨间摘要，见 digest.py）。
"""
