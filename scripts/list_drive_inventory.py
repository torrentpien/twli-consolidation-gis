"""列出社經平台村里資料 Drive 共享資料夾的完整檔案盤點。

用法：
    python scripts/list_drive_inventory.py
        --service-account /path/to/service_account.json
        --root-id 1W-6ogvCN3OsncqrE64hWxoxS4P26LgfA
        --output docs/data_inventory.json

需求：
    pip install google-api-python-client google-auth

輸出格式（docs/data_inventory.json）：
    {
      "200909": {
        "folder_id": "1w4Go...",
        "files": [
          {"name": "...", "id": "...", "size_kb": 605, "topic": "人口統計"},
          ...
        ]
      },
      ...
    }

接著可用 scripts/build_inventory_matrix.py 把 JSON 轉成覆蓋矩陣。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


# 21 個目標時點資料夾 ID（從 Drive root 列出時即已掌握）
TARGET_FOLDERS = {
    "200909": "1w4GoMc7DP0QIxEFda0piNaukwxEdALKR",
    "201009": "16G7Te_qSKRh3QrgYxG81jUA-EdJSyx_C",
    "201012": "1d-h2zAONqo9IlTcNI-GfaFN2Jeh4h_JM",
    "201112": "16bquTaqWpLrcBMkF93Oy3VBeJkq29kHN",
    "201212": "1mCqdXBtVP-rR8hyKUdhWfiopsfKtrqoG",
    "201312": "1sVkfvW017xJMjmyN5f8C45WEWYIvrs-d",
    "201409": "1PjeasfYqqx2_XhJ1bgqivWVZcKP24rfb",
    "201412": "1UwHmtpicE5-oGxW_inXha1b38v-yzRQG",
    "201512": "1CgiIHMoO2soqVRsXxeUiEzJ5hFa6R5Fx",
    "201612": "1o6uGfJEbv0yHUtdMV7JTeHjVshGq1HVP",
    "201712": "1OUdrc7oSRnTz1n7oNwPwRZdEeZnFzYXw",
    "201809": "1JphruN8oe6aQrT9MfXyMtQERwMg_eLQx",
    "201812": "18CrRiTUHniDgxkGlYUvgZdIAZm1jTftM",
    "201912": "1YaZxSWCY7NYxVUmyV1WTIV-iPStwfPz8",
    "202003": "1H0AStHzndarTqEvvm5HS4i9Y90e1L1ca",
    "202006": "1whiChDG1CPqYJFta6YzsAEg4jBmButJ3",
    "202012": "12zLdg074gf517g7ApIhffkhFnNMttB-l",
    "202112": "1uxP_8v_MM_mpPw78-1XprDDKA0U5HdDe",
    "202212": "1JpwrqEPOv3VfWaBhIrHz6zNuHcnDXFsb",
    "202312": "1GfUWY5twfVc8YrOm6MI8W369bL1GewRW",
    "202412": "1JxKDTnVEV2mek88UV6U0rk39w_1abyGR",
}


TOPIC_PATTERNS = [
    ("人口指標", r"行政區人口指標"),
    ("人口統計", r"行政區人口統計"),
    ("三段年齡", r"行政區三段年齡組性別人口統計"),
    ("五歲年齡", r"行政區五歲年齡組性別人口統計"),
    ("十歲年齡", r"行政區十歲年齡組性別人口統計"),
    ("分齡兒少", r"行政區分齡兒童及少年性別人口統計"),
    ("原住民人口", r"行政區原住民人口統計"),
    ("原住民指標", r"行政區原住民人口指標"),
    ("原住民十歲", r"行政區原住民十歲年齡組性別人口統計"),
    ("教育程度", r"行政區15歲以上人口教育程度統計"),
]


def detect_topic(filename: str) -> str:
    for topic, pattern in TOPIC_PATTERNS:
        if re.search(pattern, filename):
            return topic
    return "其他"


def list_folder(service, folder_id: str) -> list[dict]:
    files: list[dict] = []
    page_token: str | None = None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and mimeType = 'text/csv' and trashed = false",
            fields="nextPageToken, files(id, name, size, modifiedTime)",
            pageSize=200,
            pageToken=page_token,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--service-account",
        required=True,
        help="Path to Google service account JSON. The service account must be invited "
        "to the shared folder (Viewer is enough).",
    )
    parser.add_argument(
        "--output",
        default="docs/data_inventory.json",
        help="Output JSON path (default: docs/data_inventory.json)",
    )
    args = parser.parse_args()

    # Lazy import: avoid hard dep when script is just inspected.
    from google.oauth2 import service_account  # type: ignore
    from googleapiclient.discovery import build  # type: ignore

    creds = service_account.Credentials.from_service_account_file(
        args.service_account,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    service = build("drive", "v3", credentials=creds)

    inventory: dict[str, dict] = {}
    for snapshot, folder_id in TARGET_FOLDERS.items():
        files = list_folder(service, folder_id)
        inventory[snapshot] = {
            "folder_id": folder_id,
            "files": [
                {
                    "name": f["name"],
                    "id": f["id"],
                    "size_kb": int(int(f.get("size", 0)) / 1024),
                    "topic": detect_topic(f["name"]),
                }
                for f in files
            ],
        }
        topics = {f["topic"] for f in inventory[snapshot]["files"]}
        print(f"{snapshot}: {len(files)} csv, topics={sorted(topics)}")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(inventory, ensure_ascii=False, indent=2))
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
