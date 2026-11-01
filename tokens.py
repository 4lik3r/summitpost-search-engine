import os

import tiktoken  # pip install tiktoken  (https://github.com/openai/tiktoken)

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
HTML_DIR = os.path.join(DATA, "html")  # only the Mountain/Rock pages
OUT = os.path.join(DATA, "token_stats.txt")  # the result is saved here too, so we dont lose it

# the tokenizer of GPT-4 / GPT-3.5, it splits text into tokens the way the model reads it
ENCODING = tiktoken.get_encoding("cl100k_base")


def main():
    files = tokens = 0
    for file in os.listdir(HTML_DIR):
        with open(os.path.join(HTML_DIR, file), encoding="utf-8") as f:
            # disallowed_special=() so a "<|endoftext|>" written on a page is counted as normal text
            tokens += len(ENCODING.encode(f.read(), disallowed_special=()))
        files += 1
        if files % 500 == 0:
            print(f"{files} files, {tokens:,} tokens")

    result = (f"Mountain/Rock pages: {files:,}\n"
              f"Tokens (tiktoken, cl100k_base): {tokens:,}\n"
              f"Tokens per page: {tokens // max(files, 1):,}\n")
    print("\n" + result)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"Saved to {OUT}")


if __name__ == "__main__":
    main()
