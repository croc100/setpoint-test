import json
import os
import re
import time
import random
import datetime as dt
import ssl
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup

# SSL 경고 제거 (콘솔 청소)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 0. 공통 데이터 규격 (RawTournament)
# ==========================================

@dataclass
class RawTournament:
    source: str
    external_id: str
    name: str
    region_raw: str = ""
    start_date: Optional[str] = None  # JSON 저장용 (YYYY-MM-DD)
    end_date: Optional[str] = None
    original_url: str = ""
    venue: str = ""
    category: str = ""

# Sponet용 SSL 우회 어댑터
class SSLAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl._create_unverified_context()
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

# ==========================================
# 1. 사이트별 컬렉터 (주신 로직 100% 이식)
# ==========================================

class BaseCollector:
    def __init__(self, session: requests.Session):
        self.session = session
        self.source_name = ""

    def fetch(self) -> List[RawTournament]:
        raise NotImplementedError

    def _to_iso(self, d: Optional[dt.date]) -> Optional[str]:
        return d.isoformat() if d else None

class BaefCollector(BaseCollector):
    """1. 배프 (UUID 및 공문 날짜 파싱)"""
    def __init__(self, session):
        super().__init__(session)
        self.source_name = "BAEF"
        self.DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")
        self.UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

    def fetch(self):
        list_url = "https://www.badmintonfriends.co.kr/contest"
        resp = self.session.get(list_url, timeout=10)
        soup = BeautifulSoup(resp.content.decode("utf-8", errors="replace"), "lxml")
        
        urls = set()
        for a in soup.find_all("a", href=True):
            full = urljoin(list_url, a["href"])
            path = full.split("/")[-1]
            if self.UUID_RE.fullmatch(path): urls.add(full)
            
        results = []
        for url in sorted(urls):
            r = self.session.get(url, timeout=10)
            html = r.content.decode("utf-8", errors="replace")
            m = self.DATE_RE.search(html)
            d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
            
            s = BeautifulSoup(html, "lxml")
            name = s.find("h1").get_text(strip=True) if s.find("h1") else url
            
            results.append(RawTournament(
                source=self.source_name, external_id=url.split("/")[-1],
                name=name, start_date=self._to_iso(d), end_date=self._to_iso(d), original_url=url
            ))
        return results

class FacecockCollector(BaseCollector):
    """2. 페이스콕 (상세 테이블 값 추출 로직)"""
    def __init__(self, session):
        super().__init__(session)
        self.source_name = "FACECOK"
        self.base = "https://facecock.co.kr"

    def _parse_range(self, text):
        nums = re.findall(r"\d+", text)
        if len(nums) < 3: return None, None
        try:
            s = dt.date(int(nums[0]), int(nums[1]), int(nums[2]))
            e = dt.date(int(nums[3]), int(nums[4]), int(nums[5])) if len(nums) >= 6 else s
            return self._to_iso(s), self._to_iso(e)
        except: return None, None

    def _extract_val(self, soup, label):
        node = soup.find(string=re.compile(rf"\s*{label}\s*"))
        if not node: return ""
        tr = node.find_parent("tr")
        if not tr: return ""
        vals = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"]) if node not in list(c.stripped_strings)]
        return " ".join(vals).strip()

    def fetch(self):
        results = []
        for p in range(1, 3):
            url = f"{self.base}/page/index.php?page={p}&pid=game"
            soup = BeautifulSoup(self.session.get(url).text, "lxml")
            for a in soup.find_all("a", href=re.compile(r"ga_id=")):
                eid = re.search(r"ga_id=(\d+)", a['href']).group(1)
                d_url = urljoin(self.base, a['href'])
                # 상세 페이지 파싱
                dsoup = BeautifulSoup(self.session.get(d_url).text, "lxml")
                start, end = self._parse_range(self._extract_val(dsoup, "대회기간"))
                results.append(RawTournament(
                    source=self.source_name, external_id=eid, name=a.get_text(strip=True),
                    region_raw=self._extract_val(dsoup, "대회지역"), start_date=start, end_date=end,
                    original_url=d_url, venue=self._extract_val(dsoup, "대회장소")
                ))
        return results

class NearmintonCollector(BaseCollector):
    """3. 니어민턴 (이전 형제 노드 탐색 로직)"""
    def __init__(self, session):
        super().__init__(session)
        self.source_name = "NEARMINTON"

    def fetch(self):
        resp = self.session.get("https://nearminton.com/competition_list.php")
        soup = BeautifulSoup(resp.text, "lxml")
        results = []
        for txt in soup.find_all(string=re.compile("대회 시작일")):
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})", txt)
            link = txt.parent.find_previous("a", href=re.compile("competition_view"))
            if m and link:
                results.append(RawTournament(
                    source=self.source_name, external_id=link['href'], name=link.get_text(strip=True),
                    start_date=m.group(0), original_url="https://nearminton.com/"+link['href'].lstrip('/')
                ))
        return results

class SponetCollector(BaseCollector):
    """4. 스포넷 (API 통신 및 날짜 보정 로직)"""
    def __init__(self, session):
        super().__init__(session)
        self.source_name = "SPONET"
        self.session.mount("https://", SSLAdapter())
        self.session.verify = False

    def fetch(self):
        api = "https://sponet.co.kr/php/bm/mobile_tm_list.php"
        payload = {"DATA": json.dumps({"schGrade":"10","GRADE":"*","pageStart":"0","pageLimit":"50"})}
        resp = self.session.post(api, data=payload, timeout=10)
        results = []
        for t in resp.json():
            tid = t.get("TOURNAMENT_ID")
            sd = t.get("TOUR_DATE_FROM")
            results.append(RawTournament(
                source=self.source_name, external_id=tid, name=t.get("TOURNAMENT_NM"),
                start_date=f"{sd[:4]}-{sd[4:6]}-{sd[6:8]}" if sd else None,
                original_url=f"https://sponet.co.kr/php/bm/mobile_tm_view.php?TOURNAMENT_ID={tid}"
            ))
        return results

class WekkukCollector(BaseCollector):
    """5. 위꾹 (페이징 및 onclick ID 추출 로직)"""
    def __init__(self, session):
        super().__init__(session)
        self.source_name = "WEEKUK"

    def fetch(self):
        results = []
        for p in range(1, 2): # 예시로 1페이지만
            resp = self.session.get(f"https://app2.wekkuk.com/index.php/v2/contest_badminton/contest?page={p}")
            soup = BeautifulSoup(resp.text, "lxml")
            for card in soup.select(".game-list .gm-top"):
                m = re.search(r"goto_contest_view\((\d+)", card.get("onclick", ""))
                if m:
                    eid = m.group(1)
                    results.append(RawTournament(
                        source=self.source_name, external_id=eid,
                        name=card.select_one(".gm-title").get_text(strip=True),
                        original_url=f"https://app2.wekkuk.com/index.php/v2/contest_badminton/contest/{eid}"
                    ))
        return results

# ==========================================
# 2. 실행 매니저 (Collector Manager)
# ==========================================

class CollectorManager:
    def __init__(self):
        self.out_dir = Path("data/raw")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
        
        # 콜렉터 리스트 등록
        self.collectors = [
            BaefCollector(self.session),
            FacecockCollector(self.session),
            NearmintonCollector(self.session),
            SponetCollector(self.session),
            WekkukCollector(self.session)
        ]

    def run(self):
        print(f"[*] Starting Setpoint Collector Engine: {dt.datetime.now()}")
        for col in self.collectors:
            try:
                print(f"[*] Scraping {col.source_name}...")
                data = col.fetch()
                self._save(col.source_name, data)
                print(f"[v] {col.source_name} success: {len(data)} items.")
                time.sleep(random.uniform(1, 2)) # N100 부하 조절
            except Exception as e:
                print(f"[!] {col.source_name} failed: {e}")

    def _save(self, name: str, data: List[RawTournament]):
        fname = self.out_dir / f"{name.lower()}_{dt.date.today().strftime('%Y%m%d')}.jsonl"
        with open(fname, "w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")

if __name__ == "__main__":
    manager = CollectorManager()
    manager.run()