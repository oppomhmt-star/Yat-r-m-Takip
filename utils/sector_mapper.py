# utils/sector_mapper.py

"""
BIST Sektör Haritalama Modülü - Offline Versiyon

Bu modül Borsa İstanbul'da işlem gören hisselerin sektör bilgilerini
uygulama içindeki statik verilerden alır. (Hızlı ve güvenilir)
"""

from __future__ import annotations

import threading
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from functools import lru_cache
from datetime import datetime


# ============================================================================
# ENUMS
# ============================================================================

class SectorCategory(Enum):
    """Ana sektör kategorileri"""
    MALI = "Mali"
    SINAI = "Sınai"
    HIZMETLER = "Hizmetler"
    TEKNOLOJI = "Teknoloji"


class MarketType(Enum):
    """Pazar türleri"""
    YILDIZ = "Yıldız Pazar"
    ANA = "Ana Pazar"
    ALT = "Alt Pazar"
    GELISEN = "Gelişen İşletmeler Pazarı"
    YAKIN_IZLEME = "Yakın İzleme Pazarı"
    NITELIKLI = "Nitelikli Yatırımcı İşlem Pazarı"


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class CompanyInfo:
    """Şirket bilgisi"""
    symbol: str
    name: str
    sector: str
    sub_sector: Optional[str] = None
    market: Optional[MarketType] = None
    city: Optional[str] = None
    
    # Fiyat bilgileri
    last_price: Optional[float] = None
    daily_change: Optional[float] = None
    daily_change_pct: Optional[float] = None
    
    # Temel veriler
    market_cap: Optional[float] = None
    equity: Optional[float] = None
    revenue: Optional[float] = None
    net_profit: Optional[float] = None
    
    # Oranlar
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None
    
    # Endeks üyelikleri
    is_bist30: bool = False
    is_bist50: bool = False
    is_bist100: bool = False
    
    # Metadata
    last_updated: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Dictionary'e dönüştür"""
        data = asdict(self)
        if self.last_updated:
            data['last_updated'] = self.last_updated.isoformat()
        if self.market:
            data['market'] = self.market.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CompanyInfo':
        """Dictionary'den oluştur"""
        if 'last_updated' in data and data['last_updated']:
            data['last_updated'] = datetime.fromisoformat(data['last_updated'])
        if 'market' in data and data['market']:
            data['market'] = MarketType(data['market'])
        return cls(**data)


@dataclass
class SectorInfo:
    """Sektör bilgisi"""
    name: str
    category: SectorCategory
    companies: List[str] = field(default_factory=list)
    total_market_cap: float = 0.0
    avg_pe: Optional[float] = None
    avg_pb: Optional[float] = None
    
    def add_company(self, symbol: str, market_cap: float = 0):
        """Şirket ekle"""
        if symbol not in self.companies:
            self.companies.append(symbol)
            self.total_market_cap += market_cap


# ============================================================================
# FALLBACK DATA - KAPSAMLI SEKTÖR VERİLERİ
# ============================================================================

FALLBACK_SECTORS = {
    # ==========================================================================
    # BANKACILIK
    # ==========================================================================
    "AKBNK": ("Bankacılık", "Mali"),
    "ALBRK": ("Bankacılık", "Mali"),
    "DENIZ": ("Bankacılık", "Mali"),
    "GARAN": ("Bankacılık", "Mali"),
    "HALKB": ("Bankacılık", "Mali"),
    "ICBCT": ("Bankacılık", "Mali"),
    "ISCTR": ("Bankacılık", "Mali"),
    "KLNMA": ("Bankacılık", "Mali"),
    "QNBFB": ("Bankacılık", "Mali"),
    "SKBNK": ("Bankacılık", "Mali"),
    "TSKB": ("Bankacılık", "Mali"),
    "VAKBN": ("Bankacılık", "Mali"),
    "YKBNK": ("Bankacılık", "Mali"),
    "ISBTR": ("Bankacılık", "Mali"),
    "TEKST": ("Bankacılık", "Mali"),
    
    # ==========================================================================
    # SİGORTA
    # ==========================================================================
    "AGESA": ("Sigorta", "Mali"),
    "AKGRT": ("Sigorta", "Mali"),
    "ANHYT": ("Sigorta", "Mali"),
    "ANSGR": ("Sigorta", "Mali"),
    "AVIVA": ("Sigorta", "Mali"),
    "GUSGR": ("Sigorta", "Mali"),
    "HALKS": ("Sigorta", "Mali"),
    "RAYSG": ("Sigorta", "Mali"),
    "TURSG": ("Sigorta", "Mali"),
    "UFUK": ("Sigorta", "Mali"),
    
    # ==========================================================================
    # HOLDİNG VE YATIRIM
    # ==========================================================================
    "AGHOL": ("Holding ve Yatırım", "Mali"),
    "ALARK": ("Holding ve Yatırım", "Mali"),
    "BOYP": ("Holding ve Yatırım", "Mali"),
    "DOHOL": ("Holding ve Yatırım", "Mali"),
    "ECZYT": ("Holding ve Yatırım", "Mali"),
    "GLYHO": ("Holding ve Yatırım", "Mali"),
    "GOZDE": ("Holding ve Yatırım", "Mali"),
    "GSDHO": ("Holding ve Yatırım", "Mali"),
    "HURGZ": ("Holding ve Yatırım", "Mali"),
    "IHEVA": ("Holding ve Yatırım", "Mali"),
    "IHLAS": ("Holding ve Yatırım", "Mali"),
    "ISMEN": ("Holding ve Yatırım", "Mali"),
    "ITTFH": ("Holding ve Yatırım", "Mali"),
    "KCHOL": ("Holding ve Yatırım", "Mali"),
    "KZBGY": ("Holding ve Yatırım", "Mali"),
    "MMCAS": ("Holding ve Yatırım", "Mali"),
    "NTHOL": ("Holding ve Yatırım", "Mali"),
    "OSMEN": ("Holding ve Yatırım", "Mali"),
    "POLHO": ("Holding ve Yatırım", "Mali"),
    "RHEAG": ("Holding ve Yatırım", "Mali"),
    "SAHOL": ("Holding ve Yatırım", "Mali"),
    "SRVGY": ("Holding ve Yatırım", "Mali"),
    "TAHOMA": ("Holding ve Yatırım", "Mali"),
    "TAVHL": ("Holding ve Yatırım", "Mali"),
    "TKFEN": ("Holding ve Yatırım", "Mali"),
    "VERTU": ("Holding ve Yatırım", "Mali"),
    "YESIL": ("Holding ve Yatırım", "Mali"),
    "ZOREN": ("Holding ve Yatırım", "Mali"),
    
    # ==========================================================================
    # GAYRİMENKUL YATIRIM ORTAKLIKLARI (GYO)
    # ==========================================================================
    "AGYO": ("GYO", "Mali"),
    "AKMGY": ("GYO", "Mali"),
    "ALGYO": ("GYO", "Mali"),
    "ATAGY": ("GYO", "Mali"),
    "AVGYO": ("GYO", "Mali"),
    "AVPGY": ("GYO", "Mali"),
    "DGGYO": ("GYO", "Mali"),
    "DZGYO": ("GYO", "Mali"),
    "ECILC": ("GYO", "Mali"),
    "EGGYO": ("GYO", "Mali"),
    "EKGYO": ("GYO", "Mali"),
    "EMLAK": ("GYO", "Mali"),
    "GYGYO": ("GYO", "Mali"),
    "HLGYO": ("GYO", "Mali"),
    "ISGYO": ("GYO", "Mali"),
    "KLGYO": ("GYO", "Mali"),
    "KRGYO": ("GYO", "Mali"),
    "KZGYO": ("GYO", "Mali"),
    "MITRA": ("GYO", "Mali"),
    "MRGYO": ("GYO", "Mali"),
    "NUGYO": ("GYO", "Mali"),
    "OZKGY": ("GYO", "Mali"),
    "PAGYO": ("GYO", "Mali"),
    "PEGYO": ("GYO", "Mali"),
    "PEKGY": ("GYO", "Mali"),
    "RYGYO": ("GYO", "Mali"),
    "SNGYO": ("GYO", "Mali"),
    "TDGYO": ("GYO", "Mali"),
    "TRGYO": ("GYO", "Mali"),
    "TSGYO": ("GYO", "Mali"),
    "VAKGYO": ("GYO", "Mali"),
    "VKGYO": ("GYO", "Mali"),
    "VRGYO": ("GYO", "Mali"),
    "YEOTK": ("GYO", "Mali"),
    "YGYO": ("GYO", "Mali"),
    "YGGYO": ("GYO", "Mali"),
    "ZRGYO": ("GYO", "Mali"),
    "KUYAS": ("GYO", "Mali"),
    
    # ==========================================================================
    # FİNANSAL KİRALAMA VE FAKTORİNG
    # ==========================================================================
    "GLBMD": ("Finansal Kiralama ve Faktoring", "Mali"),
    "GDKMD": ("Finansal Kiralama ve Faktoring", "Mali"),
    "IEYHO": ("Finansal Kiralama ve Faktoring", "Mali"),
    "INFO": ("Finansal Kiralama ve Faktoring", "Mali"),
    "ISFIN": ("Finansal Kiralama ve Faktoring", "Mali"),
    "ISKPL": ("Finansal Kiralama ve Faktoring", "Mali"),
    "ISYAT": ("Finansal Kiralama ve Faktoring", "Mali"),
    "LIDFA": ("Finansal Kiralama ve Faktoring", "Mali"),
    "MTRYO": ("Finansal Kiralama ve Faktoring", "Mali"),
    "OYAKF": ("Finansal Kiralama ve Faktoring", "Mali"),
    "TEFAS": ("Finansal Kiralama ve Faktoring", "Mali"),
    "TEZHO": ("Finansal Kiralama ve Faktoring", "Mali"),
    "VKFYO": ("Finansal Kiralama ve Faktoring", "Mali"),
    "YKFIN": ("Finansal Kiralama ve Faktoring", "Mali"),
    
    # ==========================================================================
    # ANA METAL SANAYİ
    # ==========================================================================
    "BRSAN": ("Ana Metal Sanayi", "Sınai"),
    "BURCE": ("Ana Metal Sanayi", "Sınai"),
    "BURVA": ("Ana Metal Sanayi", "Sınai"),
    "CELHA": ("Ana Metal Sanayi", "Sınai"),
    "CEMTS": ("Ana Metal Sanayi", "Sınai"),
    "CUSAN": ("Ana Metal Sanayi", "Sınai"),
    "DMSAS": ("Ana Metal Sanayi", "Sınai"),
    "EREGL": ("Ana Metal Sanayi", "Sınai"),
    "FMIZP": ("Ana Metal Sanayi", "Sınai"),
    "ISDMR": ("Ana Metal Sanayi", "Sınai"),
    "IZDMC": ("Ana Metal Sanayi", "Sınai"),
    "IZMDC": ("Ana Metal Sanayi", "Sınai"),
    "IZFAS": ("Ana Metal Sanayi", "Sınai"),
    "JANTS": ("Ana Metal Sanayi", "Sınai"),
    "KRDMD": ("Ana Metal Sanayi", "Sınai"),
    "KARSN": ("Ana Metal Sanayi", "Sınai"),
    "OZBAL": ("Ana Metal Sanayi", "Sınai"),
    "SARKY": ("Ana Metal Sanayi", "Sınai"),
    "TUCLK": ("Ana Metal Sanayi", "Sınai"),
    "CDCLS": ("Ana Metal Sanayi", "Sınai"),
    "DOCTR": ("Ana Metal Sanayi", "Sınai"),
    
    # ==========================================================================
    # METAL EŞYA MAKİNE
    # ==========================================================================
    "AYES": ("Metal Eşya Makine", "Sınai"),
    "BALAT": ("Metal Eşya Makine", "Sınai"),
    "BFREN": ("Metal Eşya Makine", "Sınai"),
    "BKMGD": ("Metal Eşya Makine", "Sınai"),
    "BLKOM": ("Metal Eşya Makine", "Sınai"),
    "BMSCH": ("Metal Eşya Makine", "Sınai"),
    "BSHEV": ("Metal Eşya Makine", "Sınai"),
    "DITAS": ("Metal Eşya Makine", "Sınai"),
    "EGEEN": ("Metal Eşya Makine", "Sınai"),
    "EKSUN": ("Metal Eşya Makine", "Sınai"),
    "EMKEL": ("Metal Eşya Makine", "Sınai"),
    "EMNIS": ("Metal Eşya Makine", "Sınai"),
    "EPLAS": ("Metal Eşya Makine", "Sınai"),
    "EYGYO": ("Metal Eşya Makine", "Sınai"),
    "FEDTR": ("Metal Eşya Makine", "Sınai"),
    "FORMT": ("Metal Eşya Makine", "Sınai"),
    "GESAN": ("Metal Eşya Makine", "Sınai"),
    "HATSN": ("Metal Eşya Makine", "Sınai"),
    "HIDRA": ("Metal Eşya Makine", "Sınai"),
    "IHMAD": ("Metal Eşya Makine", "Sınai"),
    "IMASM": ("Metal Eşya Makine", "Sınai"),
    "INTEM": ("Metal Eşya Makine", "Sınai"),
    "IZINV": ("Metal Eşya Makine", "Sınai"),
    "KATMR": ("Metal Eşya Makine", "Sınai"),
    "KLMSN": ("Metal Eşya Makine", "Sınai"),
    "KLSYN": ("Metal Eşya Makine", "Sınai"),
    "KUTPO": ("Metal Eşya Makine", "Sınai"),
    "MAKTK": ("Metal Eşya Makine", "Sınai"),
    "MANAS": ("Metal Eşya Makine", "Sınai"),
    "MTRKS": ("Metal Eşya Makine", "Sınai"),
    "OBASE": ("Metal Eşya Makine", "Sınai"),
    "ORGE": ("Metal Eşya Makine", "Sınai"),
    "PARSN": ("Metal Eşya Makine", "Sınai"),
    "PRKAB": ("Metal Eşya Makine", "Sınai"),
    "PRZMA": ("Metal Eşya Makine", "Sınai"),
    "RUBNS": ("Metal Eşya Makine", "Sınai"),
    "SAFKR": ("Metal Eşya Makine", "Sınai"),
    "SILVR": ("Metal Eşya Makine", "Sınai"),
    "SNKRN": ("Metal Eşya Makine", "Sınai"),
    "TATGD": ("Metal Eşya Makine", "Sınai"),
    "TMSN": ("Metal Eşya Makine", "Sınai"),
    "TMPOL": ("Metal Eşya Makine", "Sınai"),
    "TEZOL": ("Metal Eşya Makine", "Sınai"),
    
    # ==========================================================================
    # TAŞIT ARAÇLARI
    # ==========================================================================
    "ASUZU": ("Otomotiv", "Sınai"),
    "DOAS": ("Otomotiv", "Sınai"),
    "FROTO": ("Otomotiv", "Sınai"),
    "OTKAR": ("Otomotiv", "Sınai"),
    "OTOKC": ("Otomotiv", "Sınai"),
    "TOASO": ("Otomotiv", "Sınai"),
    "TTRAK": ("Otomotiv", "Sınai"),
    
    # ==========================================================================
    # GIDA İÇKİ
    # ==========================================================================
    "AEFES": ("Gıda İçki", "Sınai"),
    "AVOD": ("Gıda İçki", "Sınai"),
    "BANVT": ("Gıda İçki", "Sınai"),
    "CCOLA": ("Gıda İçki", "Sınai"),
    "DARDL": ("Gıda İçki", "Sınai"),
    "EKIZ": ("Gıda İçki", "Sınai"),
    "ERSU": ("Gıda İçki", "Sınai"),
    "FADE": ("Gıda İçki", "Sınai"),
    "FRIGO": ("Gıda İçki", "Sınai"),
    "KENT": ("Gıda İçki", "Sınai"),
    "KERVT": ("Gıda İçki", "Sınai"),
    "KNFRT": ("Gıda İçki", "Sınai"),
    "KRSTL": ("Gıda İçki", "Sınai"),
    "KRSAN": ("Gıda İçki", "Sınai"),
    "KUVVA": ("Gıda İçki", "Sınai"),
    "MERKO": ("Gıda İçki", "Sınai"),
    "OYLUM": ("Gıda İçki", "Sınai"),
    "PENGD": ("Gıda İçki", "Sınai"),
    "PETUN": ("Gıda İçki", "Sınai"),
    "PINSU": ("Gıda İçki", "Sınai"),
    "PKENT": ("Gıda İçki", "Sınai"),
    "PNSUT": ("Gıda İçki", "Sınai"),
    "SELGD": ("Gıda İçki", "Sınai"),
    "TBORG": ("Gıda İçki", "Sınai"),
    "TKURU": ("Gıda İçki", "Sınai"),
    "TUKAS": ("Gıda İçki", "Sınai"),
    "ULKER": ("Gıda İçki", "Sınai"),
    "ULUUN": ("Gıda İçki", "Sınai"),
    "VANGD": ("Gıda İçki", "Sınai"),
    
    # ==========================================================================
    # KİMYA İLAÇ PETROL
    # ==========================================================================
    "ACSEL": ("Kimya İlaç Petrol", "Sınai"),
    "AKKIM": ("Kimya İlaç Petrol", "Sınai"),
    "AKSA": ("Kimya İlaç Petrol", "Sınai"),
    "ALKIM": ("Kimya İlaç Petrol", "Sınai"),
    "ANELE": ("Kimya İlaç Petrol", "Sınai"),
    "AYGAZ": ("Kimya İlaç Petrol", "Sınai"),
    "BAGFS": ("Kimya İlaç Petrol", "Sınai"),
    "BIOEN": ("Kimya İlaç Petrol", "Sınai"),
    "BOBET": ("Kimya İlaç Petrol", "Sınai"),
    "BRISA": ("Kimya İlaç Petrol", "Sınai"),
    "BRKSN": ("Kimya İlaç Petrol", "Sınai"),
    "DEVA": ("Kimya İlaç Petrol", "Sınai"),
    "DYOBY": ("Kimya İlaç Petrol", "Sınai"),
    "EGGUB": ("Kimya İlaç Petrol", "Sınai"),
    "EGEPO": ("Kimya İlaç Petrol", "Sınai"),
    "EGPRO": ("Kimya İlaç Petrol", "Sınai"),
    "GEDZA": ("Kimya İlaç Petrol", "Sınai"),
    "GENIL": ("Kimya İlaç Petrol", "Sınai"),
    "GOODY": ("Kimya İlaç Petrol", "Sınai"),
    "GUBRF": ("Kimya İlaç Petrol", "Sınai"),
    "HEKTS": ("Kimya İlaç Petrol", "Sınai"),
    "IPEKE": ("Kimya İlaç Petrol", "Sınai"),
    "LKMNH": ("Kimya İlaç Petrol", "Sınai"),
    "MRSHL": ("Kimya İlaç Petrol", "Sınai"),
    "NUHCM": ("Kimya İlaç Petrol", "Sınai"),
    "PETKM": ("Kimya İlaç Petrol", "Sınai"),
    "PRKME": ("Kimya İlaç Petrol", "Sınai"),
    "SANKO": ("Kimya İlaç Petrol", "Sınai"),
    "SASA": ("Kimya İlaç Petrol", "Sınai"),
    "SELEC": ("Kimya İlaç Petrol", "Sınai"),
    "SUMAS": ("Kimya İlaç Petrol", "Sınai"),
    "TRCAS": ("Kimya İlaç Petrol", "Sınai"),
    "TUPRS": ("Kimya İlaç Petrol", "Sınai"),
    "ULUSE": ("Kimya İlaç Petrol", "Sınai"),
    
    # ==========================================================================
    # TAŞ VE TOPRAĞA DAYALI
    # ==========================================================================
    "ADANA": ("Taş ve Toprağa Dayalı", "Sınai"),
    "ADNAC": ("Taş ve Toprağa Dayalı", "Sınai"),
    "AFYON": ("Taş ve Toprağa Dayalı", "Sınai"),
    "AKCNS": ("Taş ve Toprağa Dayalı", "Sınai"),
    "ANACM": ("Taş ve Toprağa Dayalı", "Sınai"),
    "ASLAN": ("Taş ve Toprağa Dayalı", "Sınai"),
    "BASCM": ("Taş ve Toprağa Dayalı", "Sınai"),
    "BTCIM": ("Taş ve Toprağa Dayalı", "Sınai"),
    "BOLUC": ("Taş ve Toprağa Dayalı", "Sınai"),
    "BSOKE": ("Taş ve Toprağa Dayalı", "Sınai"),
    "BUCIM": ("Taş ve Toprağa Dayalı", "Sınai"),
    "CIMSA": ("Taş ve Toprağa Dayalı", "Sınai"),
    "CMBTN": ("Taş ve Toprağa Dayalı", "Sınai"),
    "CMENT": ("Taş ve Toprağa Dayalı", "Sınai"),
    "DENCM": ("Taş ve Toprağa Dayalı", "Sınai"),
    "EGCYH": ("Taş ve Toprağa Dayalı", "Sınai"),
    "EGCYO": ("Taş ve Toprağa Dayalı", "Sınai"),
    "EGSER": ("Taş ve Toprağa Dayalı", "Sınai"),
    "GOLTS": ("Taş ve Toprağa Dayalı", "Sınai"),
    "KONYA": ("Taş ve Toprağa Dayalı", "Sınai"),
    "MRDIN": ("Taş ve Toprağa Dayalı", "Sınai"),
    "NIBAS": ("Taş ve Toprağa Dayalı", "Sınai"),
    "OYAKC": ("Taş ve Toprağa Dayalı", "Sınai"),
    "SISE": ("Taş ve Toprağa Dayalı", "Sınai"),
    "TRKCM": ("Taş ve Toprağa Dayalı", "Sınai"),
    "UNYEC": ("Taş ve Toprağa Dayalı", "Sınai"),
    "USAK": ("Taş ve Toprağa Dayalı", "Sınai"),
    
    # ==========================================================================
    # DOKUMA GİYİM DERİ
    # ==========================================================================
    "ARSAN": ("Dokuma Giyim Deri", "Sınai"),
    "ATEKS": ("Dokuma Giyim Deri", "Sınai"),
    "BLCYT": ("Dokuma Giyim Deri", "Sınai"),
    "BOSSA": ("Dokuma Giyim Deri", "Sınai"),
    "BRMEN": ("Dokuma Giyim Deri", "Sınai"),
    "DAGI": ("Dokuma Giyim Deri", "Sınai"),
    "DERAS": ("Dokuma Giyim Deri", "Sınai"),
    "DERIM": ("Dokuma Giyim Deri", "Sınai"),
    "DESA": ("Dokuma Giyim Deri", "Sınai"),
    "DGKLB": ("Dokuma Giyim Deri", "Sınai"),
    "DIRIT": ("Dokuma Giyim Deri", "Sınai"),
    "ESEMS": ("Dokuma Giyim Deri", "Sınai"),
    "HATEK": ("Dokuma Giyim Deri", "Sınai"),
    "KORDS": ("Dokuma Giyim Deri", "Sınai"),
    "KRTEK": ("Dokuma Giyim Deri", "Sınai"),
    "LUKSK": ("Dokuma Giyim Deri", "Sınai"),
    "MAVI": ("Dokuma Giyim Deri", "Sınai"),
    "MNDRS": ("Dokuma Giyim Deri", "Sınai"),
    "RODRG": ("Dokuma Giyim Deri", "Sınai"),
    "SKTAS": ("Dokuma Giyim Deri", "Sınai"),
    "SNPAM": ("Dokuma Giyim Deri", "Sınai"),
    "VAKKO": ("Dokuma Giyim Deri", "Sınai"),
    "YATAS": ("Dokuma Giyim Deri", "Sınai"),
    "YUNSA": ("Dokuma Giyim Deri", "Sınai"),
    
    # ==========================================================================
    # ORMAN KAĞIT BASIM
    # ==========================================================================
    "ADEL": ("Orman Kağıt Basım", "Sınai"),
    "BAKAB": ("Orman Kağıt Basım", "Sınai"),
    "DOCO": ("Orman Kağıt Basım", "Sınai"),
    "DURDO": ("Orman Kağıt Basım", "Sınai"),
    "IHGZT": ("Orman Kağıt Basım", "Sınai"),
    "IHYAY": ("Orman Kağıt Basım", "Sınai"),
    "KAPLM": ("Orman Kağıt Basım", "Sınai"),
    "KARTN": ("Orman Kağıt Basım", "Sınai"),
    "OLMIP": ("Orman Kağıt Basım", "Sınai"),
    "SAMAT": ("Orman Kağıt Basım", "Sınai"),
    "SEYKM": ("Orman Kağıt Basım", "Sınai"),
    "TIRE": ("Orman Kağıt Basım", "Sınai"),
    "VKING": ("Orman Kağıt Basım", "Sınai"),
    "YONGA": ("Orman Kağıt Basım", "Sınai"),
    
    # ==========================================================================
    # DAYANIKLI TÜKETİM
    # ==========================================================================
    "ALTNY": ("Dayanıklı Tüketim", "Sınai"),
    "ARCLK": ("Dayanıklı Tüketim", "Sınai"),
    "BEKO": ("Dayanıklı Tüketim", "Sınai"),
    "VESBE": ("Dayanıklı Tüketim", "Sınai"),
    "VESTL": ("Dayanıklı Tüketim", "Sınai"),
    
    # ==========================================================================
    # MADENCİLİK
    # ==========================================================================
    "CEMAS": ("Madencilik", "Sınai"),
    "ETYAT": ("Madencilik", "Sınai"),
    "IZTAR": ("Madencilik", "Sınai"),
    "KOZAA": ("Madencilik", "Sınai"),
    "KOZAL": ("Madencilik", "Sınai"),
    "MAALT": ("Madencilik", "Sınai"),
    "MADEN": ("Madencilik", "Sınai"),
    
    # ==========================================================================
    # ELEKTRİK GAZ VE SU
    # ==========================================================================
    "AKENR": ("Elektrik Gaz ve Su", "Hizmetler"),
    "AKSEN": ("Elektrik Gaz ve Su", "Hizmetler"),
    "AKSUE": ("Elektrik Gaz ve Su", "Hizmetler"),
    "AKFGY": ("Elektrik Gaz ve Su", "Hizmetler"),
    "AYEN": ("Elektrik Gaz ve Su", "Hizmetler"),
    "AYDEM": ("Elektrik Gaz ve Su", "Hizmetler"),
    "CWENE": ("Elektrik Gaz ve Su", "Hizmetler"),
    "ENJSA": ("Elektrik Gaz ve Su", "Hizmetler"),
    "EUREN": ("Elektrik Gaz ve Su", "Hizmetler"),
    "HUNER": ("Elektrik Gaz ve Su", "Hizmetler"),
    "KARYE": ("Elektrik Gaz ve Su", "Hizmetler"),
    "KONTR": ("Elektrik Gaz ve Su", "Hizmetler"),
    "KTSKR": ("Elektrik Gaz ve Su", "Hizmetler"),
    "LMKDC": ("Elektrik Gaz ve Su", "Hizmetler"),
    "MAGEN": ("Elektrik Gaz ve Su", "Hizmetler"),
    "NATEN": ("Elektrik Gaz ve Su", "Hizmetler"),
    "ODAS": ("Elektrik Gaz ve Su", "Hizmetler"),
    "PAMEL": ("Elektrik Gaz ve Su", "Hizmetler"),
    
    # ==========================================================================
    # ULAŞTIRMA
    # ==========================================================================
    "BEYAZ": ("Ulaştırma", "Hizmetler"),
    "BVSAN": ("Ulaştırma", "Hizmetler"),
    "CLEBI": ("Ulaştırma", "Hizmetler"),
    "GSDDE": ("Ulaştırma", "Hizmetler"),
    "HOROZ": ("Ulaştırma", "Hizmetler"),
    "PGSUS": ("Ulaştırma", "Hizmetler"),
    "RTALB": ("Ulaştırma", "Hizmetler"),
    "RYSAS": ("Ulaştırma", "Hizmetler"),
    "THYAO": ("Ulaştırma", "Hizmetler"),
    "ULAS": ("Ulaştırma", "Hizmetler"),
    "AIRFA": ("Ulaştırma", "Hizmetler"),
    
    # ==========================================================================
    # HABERLEŞİM
    # ==========================================================================
    "KAREL": ("Haberleşme", "Hizmetler"),
    "NETAS": ("Haberleşme", "Hizmetler"),
    "TCELL": ("Haberleşme", "Hizmetler"),
    "TTKOM": ("Haberleşme", "Hizmetler"),
    
    # ==========================================================================
    # TİCARET (PERAKENDE)
    # ==========================================================================
    "BIMAS": ("Ticaret", "Hizmetler"),
    "BIZIM": ("Ticaret", "Hizmetler"),
    "CRFSA": ("Ticaret", "Hizmetler"),
    "INDES": ("Ticaret", "Hizmetler"),
    "MGROS": ("Ticaret", "Hizmetler"),
    "MIPAZ": ("Ticaret", "Hizmetler"),
    "SOKM": ("Ticaret", "Hizmetler"),
    "TGSAS": ("Ticaret", "Hizmetler"),
    
    # ==========================================================================
    # TURİZM OTELCİLİK
    # ==========================================================================
    "AVTUR": ("Turizm", "Hizmetler"),
    "AYCES": ("Turizm", "Hizmetler"),
    "ETILR": ("Turizm", "Hizmetler"),
    "MARTI": ("Turizm", "Hizmetler"),
    "MERIT": ("Turizm", "Hizmetler"),
    "METUR": ("Turizm", "Hizmetler"),
    "NTTUR": ("Turizm", "Hizmetler"),
    "PKART": ("Turizm", "Hizmetler"),
    "TEKTU": ("Turizm", "Hizmetler"),
    "UTPYA": ("Turizm", "Hizmetler"),
    
    # ==========================================================================
    # SPOR
    # ==========================================================================
    "BJKAS": ("Spor", "Hizmetler"),
    "FENER": ("Spor", "Hizmetler"),
    "GSRAY": ("Spor", "Hizmetler"),
    "TSPOR": ("Spor", "Hizmetler"),
    
    # ==========================================================================
    # SAĞLIK
    # ==========================================================================
    "BIENY": ("Sağlık", "Hizmetler"),
    "CANTE": ("Sağlık", "Hizmetler"),
    "GENSM": ("Sağlık", "Hizmetler"),
    "GEREL": ("Sağlık", "Hizmetler"),
    "MEDTR": ("Sağlık", "Hizmetler"),
    "MPARK": ("Sağlık", "Hizmetler"),
    "ONCSM": ("Sağlık", "Hizmetler"),
    "TNZTP": ("Sağlık", "Hizmetler"),
    
    # ==========================================================================
    # İNŞAAT VE BAYINDIRLIK
    # ==========================================================================
    "BMELK": ("İnşaat ve Bayındırlık", "Hizmetler"),
    "EDIP": ("İnşaat ve Bayındırlık", "Hizmetler"),
    "ELITE": ("İnşaat ve Bayındırlık", "Hizmetler"),
    "ENSA": ("İnşaat ve Bayındırlık", "Hizmetler"),
    "ENKAI": ("İnşaat ve Bayındırlık", "Hizmetler"),
    "GEDIK": ("İnşaat ve Bayındırlık", "Hizmetler"),
    "SANEL": ("İnşaat ve Bayındırlık", "Hizmetler"),
    "TURGG": ("İnşaat ve Bayındırlık", "Hizmetler"),
    "YAYLA": ("İnşaat ve Bayındırlık", "Hizmetler"),
    "YBTAS": ("İnşaat ve Bayındırlık", "Hizmetler"),
    "YYAPI": ("İnşaat ve Bayındırlık", "Hizmetler"),
    
    # ==========================================================================
    # TEKNOLOJİ
    # ==========================================================================
    "ALCTL": ("Teknoloji", "Teknoloji"),
    "ARENA": ("Teknoloji", "Teknoloji"),
    "ARDYZ": ("Teknoloji", "Teknoloji"),
    "ARMDA": ("Teknoloji", "Teknoloji"),
    "ASELS": ("Teknoloji", "Teknoloji"),
    "ATATP": ("Teknoloji", "Teknoloji"),
    "BIGCH": ("Teknoloji", "Teknoloji"),
    "DESPC": ("Teknoloji", "Teknoloji"),
    "DGATE": ("Teknoloji", "Teknoloji"),
    "EDATA": ("Teknoloji", "Teknoloji"),
    "ESCOM": ("Teknoloji", "Teknoloji"),
    "FONET": ("Teknoloji", "Teknoloji"),
    "FORTE": ("Teknoloji", "Teknoloji"),
    "INGRM": ("Teknoloji", "Teknoloji"),
    "KFEIN": ("Teknoloji", "Teknoloji"),
    "KRONT": ("Teknoloji", "Teknoloji"),
    "LINK": ("Teknoloji", "Teknoloji"),
    "LOGO": ("Teknoloji", "Teknoloji"),
    "MIATK": ("Teknoloji", "Teknoloji"),
    "PAPIL": ("Teknoloji", "Teknoloji"),
    "PRDGS": ("Teknoloji", "Teknoloji"),
    "QUAGR": ("Teknoloji", "Teknoloji"),
    "SMART": ("Teknoloji", "Teknoloji"),
    "SMRFT": ("Teknoloji", "Teknoloji"),
    "SMRTG": ("Teknoloji", "Teknoloji"),
    "TRILC": ("Teknoloji", "Teknoloji"),
    "VBTYZ": ("Teknoloji", "Teknoloji"),
    
    # ==========================================================================
    # SAVUNMA
    # ==========================================================================
    "TMSN": ("Savunma", "Teknoloji"),
    
    # ==========================================================================
    # EĞİTİM VE BASIN YAYIN
    # ==========================================================================
    "IHLGM": ("Basın Yayın", "Hizmetler"),
    
    # ==========================================================================
    # MOBİLYA
    # ==========================================================================
    "ALFAS": ("Mobilya", "Sınai"),
    "DGZTE": ("Mobilya", "Sınai"),
    "DOGUB": ("Mobilya", "Sınai"),
}


# ============================================================================
# SECTOR MAPPER CLASS - SİMPLİFİED (SADECE FALLBACK)
# ============================================================================

class SectorMapper:
    """
    Sektör haritalama sınıfı - Offline versiyon
    
    Thread-safe singleton pattern ile çalışır.
    Sadece uygulama içi statik verilerden sektör bilgisi alır.
    API çağrısı yapmaz - Maksimum hız!
    """
    
    _instance: Optional['SectorMapper'] = None
    _lock = threading.Lock()
    
    def __new__(cls, force_update: bool = False) -> 'SectorMapper':
        """Singleton pattern"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self, force_update: bool = False):
        """
        Args:
            force_update: Bu parametre artık kullanılmıyor (geriye uyumluluk için)
        """
        if self._initialized:
            return
        
        self._companies: Dict[str, CompanyInfo] = {}
        self._sectors: Dict[str, SectorInfo] = {}
        self._cache_lock = threading.RLock()
        
        # Fallback verilerini yükle (anında)
        self._load_fallback_data()
        self._initialized = True
    
    def _load_fallback_data(self) -> None:
        """Fallback verilerini yükle - Çok hızlı!"""
        for symbol, (sector, category) in FALLBACK_SECTORS.items():
            self._companies[symbol] = CompanyInfo(
                symbol=symbol,
                name=symbol,
                sector=sector,
                sub_sector=None,
                last_updated=datetime.now()
            )
            
            # Kategori enum'a dönüştür
            try:
                cat_enum = SectorCategory[category.upper().replace("İ", "I").replace("ı", "I")]
            except KeyError:
                cat_enum = SectorCategory.SINAI
            
            # Sektör bilgisini güncelle
            if sector not in self._sectors:
                self._sectors[sector] = SectorInfo(
                    name=sector,
                    category=cat_enum
                )
            self._sectors[sector].add_company(symbol)
    
    @lru_cache(maxsize=1000)
    def get_sector(self, symbol: str) -> str:
        """
        Hissenin sektörünü döndür
        
        Args:
            symbol: Hisse sembolü
            
        Returns:
            Sektör adı
        """
        symbol = symbol.upper()
        
        if symbol in self._companies:
            return self._companies[symbol].sector or "Diğer"
        
        return "Diğer"
    
    def get_company_info(self, symbol: str) -> Optional[CompanyInfo]:
        """
        Şirket bilgilerini döndür
        
        Args:
            symbol: Hisse sembolü
            
        Returns:
            CompanyInfo veya None
        """
        return self._companies.get(symbol.upper())
    
    def get_all_sectors(self) -> List[str]:
        """Tüm sektörleri döndür"""
        return sorted(self._sectors.keys())
    
    def get_sector_companies(self, sector: str) -> List[str]:
        """
        Sektördeki şirketleri döndür
        
        Args:
            sector: Sektör adı
            
        Returns:
            Şirket sembolleri listesi
        """
        if sector in self._sectors:
            return sorted(self._sectors[sector].companies)
        return []
    
    def get_sector_stats(self, sector: str) -> Optional[SectorInfo]:
        """Sektör istatistikleri"""
        return self._sectors.get(sector)
    
    def search_companies(self, query: str) -> List[CompanyInfo]:
        """
        Şirket ara (sembol veya isim)
        
        Args:
            query: Arama terimi
            
        Returns:
            Eşleşen şirketler
        """
        query = query.upper()
        results = []
        
        for symbol, company in self._companies.items():
            if (query in symbol or 
                query in company.name.upper() or
                (company.sector and query in company.sector.upper())):
                results.append(company)
        
        return results
    
    def get_market_members(self, market: MarketType) -> List[str]:
        """
        Pazar üyelerini döndür
        
        Args:
            market: Pazar tipi
            
        Returns:
            Şirket sembolleri
        """
        members = []
        for symbol, company in self._companies.items():
            if company.market == market:
                members.append(symbol)
        return sorted(members)


# ============================================================================
# PUBLIC API
# ============================================================================

# Global mapper instance
_mapper: Optional[SectorMapper] = None
_mapper_lock = threading.Lock()


def get_mapper(force_update: bool = False) -> SectorMapper:
    """Global mapper instance'ı al"""
    global _mapper
    
    with _mapper_lock:
        if _mapper is None:
            _mapper = SectorMapper()
        return _mapper


# Geriye uyumlu API fonksiyonları
@lru_cache(maxsize=1000)
def get_sector(symbol: str) -> str:
    """
    Hisse senedinin sektörünü döndür
    
    Args:
        symbol: Hisse sembolü
        
    Returns:
        Sektör adı
    """
    mapper = get_mapper()
    return mapper.get_sector(symbol)


def get_company_info(symbol: str) -> Optional[CompanyInfo]:
    """
    Şirket bilgilerini döndür
    
    Args:
        symbol: Hisse sembolü
        
    Returns:
        CompanyInfo veya None
    """
    mapper = get_mapper()
    return mapper.get_company_info(symbol)


def get_all_sectors(portfolio: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Portföydeki hisseleri sektörlere göre grupla
    
    Args:
        portfolio: Portföy listesi
        
    Returns:
        {sektör: [hisse_listesi]} sözlüğü
    """
    sectors = {}
    
    for stock in portfolio:
        symbol = stock.get('sembol', stock.get('symbol', ''))
        if not symbol:
            continue
        
        sector = get_sector(symbol)
        
        if sector not in sectors:
            sectors[sector] = []
        
        sectors[sector].append(stock)
    
    return sectors


def update_sector_data(force: bool = True) -> bool:
    """
    Sektör verilerini güncelle (artık sadece True döner)
    
    Args:
        force: Bu parametre artık kullanılmıyor
        
    Returns:
        Her zaman True
    """
    # Artık API çağrısı yapmıyoruz, veriler zaten yüklü
    return True


def get_sector_distribution(portfolio: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Portföyün sektör bazında yüzde dağılımı
    
    Args:
        portfolio: Portföy listesi
        
    Returns:
        {sektör: yüzde} sözlüğü
    """
    sectors = get_all_sectors(portfolio)
    total_value = 0.0
    sector_values = {}
    
    for sector, stocks in sectors.items():
        sector_value = sum(
            s.get('adet', 0) * s.get('guncel_fiyat', s.get('ort_maliyet', 0))
            for s in stocks
        )
        sector_values[sector] = sector_value
        total_value += sector_value
    
    if total_value > 0:
        return {
            sector: (value / total_value * 100)
            for sector, value in sector_values.items()
        }
    
    return {}