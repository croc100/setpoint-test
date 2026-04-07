# core/collectors/base.py
import requests
from abc import ABC, abstractmethod

class BaseCollector(ABC):
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 ...", # 100님의 기존 헤더 사용
        }

    def _get(self, url: str):
        resp = requests.get(url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp

    @abstractmethod
    def collect(self, url: str):
        """이 메서드를 상속받아 각 사이트별 로직 구현"""
        pass