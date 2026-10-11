import requests
import hashlib
import re
import time
import xml.etree.ElementTree as ET

from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime, parsedate_to_datetime


SOURCE_URL = "https://fukuyama.hosp.go.jp/cnt1_00143.html"
OUTPUT = Path(__file__).parent / "fukuyama_center.xml"

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )
}

MAX_RETRIES = 3

PATTERN = re.compile(
    r"センター便り\s*(20\d{2})年\s*(\d{1,2})月号"
)


# --------------------------------------------------
# HTTP取得
# --------------------------------------------------

def fetch(url):

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            print(f"取得 {attempt}/{MAX_RETRIES}")

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            print("HTTP:", response.status_code)

            response.raise_for_status()

            return response

        except requests.RequestException as e:

            print("取得失敗:", e)

            if attempt < MAX_RETRIES:

                print("10秒待って再試行します。")
                time.sleep(10)

    return None


# --------------------------------------------------
# 既存RSS読み込み
# --------------------------------------------------

old_items = {}

if OUTPUT.exists():

    try:

        tree = ET.parse(OUTPUT)

        for item in tree.getroot().findall(
            "./channel/item"
        ):

            guid = item.findtext(
                "guid",
                ""
            )

            if not guid:
                continue

            old_items[guid] = {
                "title": item.findtext(
                    "title",
                    ""
                ),
                "link": item.findtext(
                    "link",
                    ""
                ),
                "description": item.findtext(
                    "description",
                    ""
                ),
                "pubDate": item.findtext(
                    "pubDate",
                    ""
                ),
                "guid": guid,
            }

    except Exception as e:

        print("既存RSS読み込みエラー:", e)
        print("安全のため今回は更新しません。")

        raise SystemExit(0)


print(
    "既存RSS件数:",
    len(old_items)
)


# --------------------------------------------------
# ページ取得
# --------------------------------------------------

response = fetch(SOURCE_URL)

if response is None:

    print(
        "サイトを取得できないため、"
        "既存XMLを維持します。"
    )

    raise SystemExit(0)


soup = BeautifulSoup(
    response.content,
    "html.parser"
)


# --------------------------------------------------
# センター便り解析
# --------------------------------------------------

current_items = []

for a in soup.find_all(
    "a",
    href=True
):

    title = a.get_text(
        " ",
        strip=True
    )

    title = re.sub(
        r"\s+",
        " ",
        title
    ).strip()

    match = PATTERN.search(title)

    if not match:
        continue

    year = int(
        match.group(1)
    )

    month = int(
        match.group(2)
    )

    link = urljoin(
        response.url,
        a["href"]
    )

    # PDF以外は除外
    if not link.lower().endswith(
        ".pdf"
    ):
        continue

    # サイトには掲載日がないため、
    # 号の年月の1日正午をRSSの日付として使用
    pub_dt = datetime(
        year,
        month,
        1,
        12,
        0,
        0,
        tzinfo=JST
    )

    # 号そのものを一意に識別する。
    # PDFのURLが将来差し替えられても
    # 同じ号を新規記事扱いしない。
    guid_source = (
        f"fukuyama-center|"
        f"{year:04d}-{month:02d}"
    )

    guid = hashlib.sha256(
        guid_source.encode(
            "utf-8"
        )
    ).hexdigest()

    current_items.append({
        "title": (
            f"センター便り"
            f"{year}年{month}月号"
        ),
        "link": link,
        "description": (
            f"福山医療センター "
            f"センター便り "
            f"{year}年{month}月号"
        ),
        "pubDate": format_datetime(
            pub_dt
        ),
        "guid": guid,
    })


print(
    "サイトから検出:",
    len(current_items),
    "件"
)


# --------------------------------------------------
# 安全チェック
# --------------------------------------------------

if len(current_items) < 50:

    print(
        "取得件数が異常に少ないため、"
        "サイト構造変更の可能性があります。"
    )

    print(
        "既存XMLを維持します。"
    )

    raise SystemExit(0)


# --------------------------------------------------
# 重複除去
# --------------------------------------------------

unique_items = []
seen = set()

for item in current_items:

    if item["guid"] in seen:
        continue

    seen.add(
        item["guid"]
    )

    unique_items.append(
        item
    )


current_items = unique_items


print(
    "重複除去後:",
    len(current_items),
    "件"
)


# --------------------------------------------------
# 既存RSSと統合
#
# 将来公式ページから古い号が削除されても
# RSS側には残す
# --------------------------------------------------

all_items = []
seen_guids = set()


for item in current_items:

    all_items.append(
        item
    )

    seen_guids.add(
        item["guid"]
    )


for guid, item in old_items.items():

    if guid in seen_guids:
        continue

    all_items.append(
        item
    )

    seen_guids.add(
        guid
    )


# --------------------------------------------------
# 日付順
# --------------------------------------------------

def get_date(item):

    try:

        return parsedate_to_datetime(
            item["pubDate"]
        )

    except Exception:

        return datetime.min.replace(
            tzinfo=timezone.utc
        )


all_items.sort(
    key=get_date,
    reverse=True
)


# --------------------------------------------------
# RSS作成
# --------------------------------------------------

rss = ET.Element(
    "rss",
    version="2.0"
)

channel = ET.SubElement(
    rss,
    "channel"
)


ET.SubElement(
    channel,
    "title"
).text = (
    "福山医療センター センター便り"
)


ET.SubElement(
    channel,
    "link"
).text = SOURCE_URL


ET.SubElement(
    channel,
    "description"
).text = (
    "福山医療センター「センター便り」の更新情報"
)


ET.SubElement(
    channel,
    "language"
).text = "ja"


# --------------------------------------------------
# RSS記事
# --------------------------------------------------

for item in all_items:

    element = ET.SubElement(
        channel,
        "item"
    )

    ET.SubElement(
        element,
        "title"
    ).text = item["title"]

    ET.SubElement(
        element,
        "link"
    ).text = item["link"]

    ET.SubElement(
        element,
        "description"
    ).text = item["description"]

    ET.SubElement(
        element,
        "pubDate"
    ).text = item["pubDate"]

    guid_element = ET.SubElement(
        element,
        "guid"
    )

    guid_element.set(
        "isPermaLink",
        "false"
    )

    guid_element.text = item["guid"]


# --------------------------------------------------
# XML保存
# --------------------------------------------------

tree = ET.ElementTree(rss)

ET.indent(
    tree,
    space="  "
)

tree.write(
    OUTPUT,
    encoding="utf-8",
    xml_declaration=True
)


# --------------------------------------------------
# 結果表示
# --------------------------------------------------

print()
print("=" * 70)
print("RSS作成成功")
print("=" * 70)

print(
    "現在サイトから取得:",
    len(current_items),
    "件"
)

print(
    "RSS保存件数:",
    len(all_items),
    "件"
)

print(
    "保存先:",
    OUTPUT
)

print()
print("最新20件:")


for i, item in enumerate(
    all_items[:20],
    start=1
):

    print()

    print(
        f"[{i}] "
        f"{item['pubDate']} "
        f"{item['title']}"
    )

    print(
        "    ",
        item["link"]
    )