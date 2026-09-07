from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, Optional


def parse_propget_xml(xml_text: str) -> Optional[str]:
    """
    解析 `svn propget NAME --xml` 的输出。
    通常格式：
    <properties>
      <target path="...">
        <property name="svn:ignore">*.o</property>
      </target>
    </properties>
    若无属性，通常输出空或无 property 节点。
    返回属性值字符串，若未找到则返回 None。
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    # 我们通常针对单路径查询，直接找第一个 property 节点即可
    # 如果是递归查询，逻辑会更复杂，这里暂定为单路径 fetch
    prop_el = root.find(".//property")
    if prop_el is not None:
        return prop_el.text
    return None


def parse_proplist_xml(xml_text: str) -> Dict[str, str]:
    """
    解析 `svn proplist --xml` 的输出。
    返回 {prop_name: prop_value} 的字典。
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    props = {}
    # 同样假设针对单路径，或者合并所有 target 的属性
    for target in root.findall("target"):
        for prop in target.findall("property"):
            name = prop.get("name")
            value = prop.text or ""
            if name:
                props[name] = value
    return props
