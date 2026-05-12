import json
import os
from pathlib import Path

from dotenv import load_dotenv
from tavily import TavilyClient


OUTPUT_PATH = Path("data/reference/latest_nppa_search_results.json")


def main():
    load_dotenv()

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("Missing TAVILY_API_KEY in .env")

    client = TavilyClient(api_key=api_key)

    query = "NPPA coronary stent ceiling price India 2026 DES BMS"

    results = client.search(
        query=query,
        search_depth="advanced",
        max_results=5,
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"✅ Saved results to {OUTPUT_PATH}")

    for i, item in enumerate(results.get("results", []), 1):
        print()
        print(f"{i}. {item.get('title')}")
        print(item.get("url"))
        print((item.get("content") or "")[:400])


if __name__ == "__main__":
    main()