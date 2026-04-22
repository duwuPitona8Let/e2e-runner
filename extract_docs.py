#!/usr/bin/env python3
import zipfile
import xml.etree.ElementTree as ET
import os

docs = {
    "1_ТЗ_Система": "/Users/macbook/Desktop/Диплом2/Техническое задание на разработку системы автоматизации проведения сквозных юнит.docx",
    "2_ТЗ_Колмаков": "/Users/macbook/Desktop/Диплом2/Техническое задание Колмаков.docx",
    "3_ИТОГОВЫЙ": "/Users/macbook/Desktop/Диплом2/ИТОГОВЫЙ КОЛМАКОВ.docx",
    "4_Источники": "/Users/macbook/Desktop/Диплом2/Источники Колмаков.docx",
}

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

def extract_text(docx_path):
    try:
        with zipfile.ZipFile(docx_path, 'r') as zf:
            xml_data = zf.read('word/document.xml')
            root = ET.fromstring(xml_data)

            paragraphs = []
            for para in root.findall('.//w:p', NS):
                texts = []
                for t in para.findall('.//w:t', NS):
                    if t.text:
                        texts.append(t.text)
                if texts:
                    paragraphs.append(''.join(texts))

            return '\n'.join(paragraphs)
    except Exception as e:
        return f"ОШИБКА: {str(e)}"

for key, path in docs.items():
    if os.path.exists(path):
        text = extract_text(path)
        with open(f'/Users/macbook/Desktop/Диплом2/{key}_text.txt', 'w', encoding='utf-8') as f:
            f.write(text)
        print(f"✓ {key}: {len(text)} символов")
    else:
        print(f"✗ {key}: файл не найден")

print("\nГотово!")
