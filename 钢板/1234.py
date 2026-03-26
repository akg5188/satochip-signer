# -*- coding: utf-8 -*-
import sys
from pathlib import Path


def _extract_wordlist_from_steel_wallet(base_dir: Path):
    steel_wallet = base_dir / "steel_wallet.py"
    if not steel_wallet.exists():
        return None

    text = steel_wallet.read_text(encoding="utf-8")
    marker = 'BIP39_WORDLIST = """'
    start = text.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = text.find('"""', start)
    if end == -1:
        return None

    words = [w.strip() for w in text[start:end].splitlines() if w.strip()]
    return words if len(words) == 2048 else None


def get_full_wordlist():
    base_dir = Path(__file__).resolve().parent
    paths = [
        Path('/usr/share/python3-mnemonic/wordlist/english.txt'),
        base_dir / 'english.txt',
    ]
    for path in paths:
        try:
            if path.exists():
                words = [w.strip() for w in path.read_text(encoding='utf-8').splitlines() if w.strip()]
                if len(words) == 2048:
                    return words
        except Exception:
            continue

    words = _extract_wordlist_from_steel_wallet(base_dir)
    if words:
        return words

    raise RuntimeError("未找到有效的 BIP39 2048 词表，请先提供 english.txt 或 steel_wallet.py。")

def main():
    words_db = get_full_wordlist()
    if len(words_db) < 2048:
        print("❌ 错误：未能加载完整的 2048 单词表。")
        print("请将 english.txt 放在脚本旁边，或者手动编辑脚本填入单词。")
        return

    print("\n--- 助记词位移加密/解密工具 (离线版) ---")
    
    # 1. 输入处理
    raw_input = input("\n请直接粘贴你的 12 个单词 (空格隔开):\n> ")
    user_words = raw_input.strip().split()
    
    if len(user_words) != 12:
        print(f"❌ 错误：你输入了 {len(user_words)} 个词，要求是 12 个。")
        return

    offsets = [8, 7, 6, 7, 6, 7, -7, -3, -5, -2, -4, -2]

    # 3. 选择模式
    choice = input("\n请选择操作 (1: 加密位移 / 2: 还原回真词): ")
    
    result = []
    for i in range(12):
        word = user_words[i].lower()
        if word not in words_db:
            print(f"❌ 错误：单词 '{word}' 不在词库中！")
            return
        
        idx = words_db.index(word)
        shift = offsets[i] if choice == '1' else -offsets[i]
        new_idx = (idx + shift) % 2048
        result.append(words_db[new_idx])

    print("\n✅ 处理成功！结果如下：")
    print("----------------------------------------")
    print(" ".join(result))
    print("----------------------------------------")

if __name__ == "__main__":
    main()
