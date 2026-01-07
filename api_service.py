# api_service.py
"""
API servisleri modülü - isyatirimhisse ana sağlayıcı
Desteklenen: isyatirimhisse (ana), yfinance (yedek)
"""

import threading
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Callable, Any, Tuple
from dataclasses import dataclass
import pandas as pd
import numpy as np
import warnings
from functools import lru_cache
from pathlib import Path
import json
import pickle

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# İş Yatırım Hisse kontrolü
try:
    from isyatirimhisse import StockData
    IS_YATIRIM_AVAILABLE = True
    logger.info("✅ isyatirimhisse kütüphanesi hazır")
except ImportError:
    IS_YATIRIM_AVAILABLE = False
    logger.warning("⚠️ isyatirimhisse kurulu değil. pip install isyatirimhisse")

# yfinance kontrolü (fallback için)
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    logger.warning("⚠️ yfinance kurulu değil. pip install yfinance")

# Config
try:
    from config import INDICES, CURRENCIES
except ImportError:
    # Varsayılan değerler
    INDICES = {
        "BIST100": "XU100.IS",
        "BIST30": "XU030.IS",
        "S&P500": "^GSPC",
        "Nasdaq": "^IXIC",
        "DAX": "^GDAXI"
    }
    
    CURRENCIES = {
        "DOLAR": "TRY=X",
        "EURO": "EURTRY=X",
        "ALTIN": "GC=F",
        "BTC": "BTC-USD"
    }


# ============================================================================
# CONSTANTS
# ============================================================================

# Cache ayarları
CACHE_TIMEOUT = 300  # 5 dakika
CACHE_DIR = Path.home() / ".bist_api_cache"
CACHE_DIR.mkdir(exist_ok=True)

# İstek ayarları
MAX_RETRIES = 3
RETRY_DELAY = 2
MIN_REQUEST_INTERVAL = 0.5  # İstekler arası minimum süre

# Varsayılan değerler
DEFAULT_DAYS = 30
TRADING_DAYS_PER_YEAR = 252


# ============================================================================
# CACHE MANAGER
# ============================================================================

class CacheManager:
    """Thread-safe cache yöneticisi"""
    
    def __init__(self, timeout: int = CACHE_TIMEOUT):
        self._cache: Dict[str, Tuple[Any, datetime]] = {}
        self._lock = threading.RLock()
        self._timeout = timeout
        
        # Request timeout ayarları - İYİLEŞTİRİLDİ
        self._connect_timeout = 10  # Bağlantı timeout
        self._read_timeout = 30     # Okuma timeout
        
        # Disk cache
        self._disk_cache_file = CACHE_DIR / "cache.pkl"
        self._load_disk_cache()
    
    def _load_disk_cache(self):
        """Disk cache'i yükle"""
        try:
            if self._disk_cache_file.exists():
                with open(self._disk_cache_file, 'rb') as f:
                    disk_cache = pickle.load(f)
                    # Sadece geçerli olanları yükle
                    now = datetime.now()
                    for key, (value, timestamp) in disk_cache.items():
                        if (now - timestamp).seconds < self._timeout:
                            self._cache[key] = (value, timestamp)
        except Exception as e:
            logger.debug(f"Disk cache yükleme hatası: {e}")
    
    def _save_disk_cache(self):
        """Cache'i diske kaydet"""
        try:
            with open(self._disk_cache_file, 'wb') as f:
                pickle.dump(self._cache, f)
        except Exception as e:
            logger.debug(f"Disk cache kaydetme hatası: {e}")
    
    def get(self, key: str) -> Optional[Any]:
        """Cache'den veri al"""
        with self._lock:
            if key not in self._cache:
                return None
            
            data, timestamp = self._cache[key]
            if (datetime.now() - timestamp).seconds > self._timeout:
                del self._cache[key]
                return None
            
            return data
    
    def set(self, key: str, value: Any) -> None:
        """Cache'e veri kaydet"""
        with self._lock:
            self._cache[key] = (value, datetime.now())
            self._save_disk_cache()
    
    def clear(self) -> None:
        """Cache'i temizle"""
        with self._lock:
            self._cache.clear()
            if self._disk_cache_file.exists():
                self._disk_cache_file.unlink()
    
    def remove_pattern(self, pattern: str) -> None:
        """Pattern'e uyan anahtarları sil"""
        with self._lock:
            keys_to_remove = [k for k in self._cache.keys() if pattern in k]
            for key in keys_to_remove:
                del self._cache[key]


# Global cache
_cache = CacheManager()


# ============================================================================
# API SERVICE CLASS
# ============================================================================

class APIService:
    """
    İş Yatırım Hisse API Service
    
    isyatirimhisse kütüphanesi ana sağlayıcı,
    yfinance yedek sağlayıcı olarak kullanılır.
    """
    
    def __init__(self):
        """API Service başlat"""
        self.cache = _cache
        self.cache_timeout = CACHE_TIMEOUT
        self.cache_lock = threading.Lock()
        
        # İş Yatırım StockData
        self._stock_data: Optional[StockData] = None
        self._lock = threading.RLock()
        
        # Rate limiting
        self._last_request_time = 0
        self._min_request_interval = MIN_REQUEST_INTERVAL
        
        # USD/TRY kuru
        self.usd_try_rate = 34.50
        
        # İş Yatırım'ı başlat
        if IS_YATIRIM_AVAILABLE:
            try:
                self._stock_data = StockData()
                logger.info("✅ İş Yatırım StockData başlatıldı")
            except Exception as e:
                logger.error(f"❌ StockData başlatma hatası: {e}")
        
        # yfinance fallback
        self.use_yfinance_fallback = YFINANCE_AVAILABLE
        
        # Sağlayıcı durumu
        self.is_available = self._stock_data is not None
        self.provider = "isyatirimhisse" if self.is_available else "yfinance"
    
    # ========================================================================
    # RATE LIMITING & RETRY
    # ========================================================================
    
    def _rate_limit(self) -> None:
        """Rate limiting - çok sık istek atmayı önle"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()
    
    def _safe_request(self, func, *args, **kwargs) -> Optional[Any]:
        """
        Güvenli istek gönderimi (retry mekanizmalı) - İYİLEŞTİRİLDİ
        """
        last_error = None
        
        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit()
                result = func(*args, **kwargs)
                return result
                
            except (ConnectionResetError, ConnectionAbortedError, ConnectionError) as e:
                last_error = e
                print(f"Bağlantı hatası (deneme {attempt + 1}/{MAX_RETRIES}): {type(e).__name__}")
                
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_DELAY * (2 ** attempt)  # Exponential backoff: 2, 4, 8
                    print(f"⏳ {wait_time} saniye bekleniyor...")
                    time.sleep(wait_time)
                
            except Exception as e:
                last_error = e
                print(f"İstek hatası (deneme {attempt + 1}/{MAX_RETRIES}): {type(e).__name__}: {e}")
                
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
        
        # Tüm denemeler başarısız
        print(f"❌ Tüm denemeler başarısız oldu: {type(last_error).__name__}")
        return None
    
    # ========================================================================
    # İŞ YATIRIM METHODS
    # ========================================================================
    
    def _format_symbol_for_isyatirim(self, symbol: str) -> str:
        """
        Sembolü İş Yatırım formatına dönüştür
        THYAO.IS -> THYAO
        THYAO -> THYAO
        """
        return symbol.replace('.IS', '').replace('.IST', '').upper()
    
    def _get_stock_data_isyatirim(
        self, 
        symbol: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Optional[pd.DataFrame]:
        """
        İş Yatırım'dan veri çek
        
        Args:
            symbol: Hisse sembolü
            start_date: Başlangıç tarihi
            end_date: Bitiş tarihi
            
        Returns:
            DataFrame veya None
        """
        if not self.is_available:
            return None
        
        with self._lock:
            try:
                # Varsayılan tarihler
                if end_date is None:
                    end_date = datetime.now()
                if start_date is None:
                    start_date = end_date - timedelta(days=365)
                
                # Sembolü formatla
                clean_symbol = self._format_symbol_for_isyatirim(symbol)
                
                # İş Yatırım'dan veri çek
                def _fetch():
                    return self._stock_data.get_data(
                        symbols=clean_symbol,
                        start_date=start_date.strftime('%d-%m-%Y'),
                        end_date=end_date.strftime('%d-%m-%Y')
                    )
                
                data = self._safe_request(_fetch)
                
                if data is not None and not data.empty:
                    # Index'i datetime yap
                    if not isinstance(data.index, pd.DatetimeIndex):
                        data.index = pd.to_datetime(data.index)
                    
                    return data
                    
            except Exception as e:
                logger.error(f"İş Yatırım veri hatası ({symbol}): {e}")
        
        return None
    
    # ========================================================================
    # SINGLE STOCK METHODS
    # ========================================================================
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Tek hisse için güncel fiyat
        
        Args:
            symbol: Hisse sembolü
            
        Returns:
            Güncel fiyat veya None
        """
        cache_key = f"price_{symbol}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        
        # İş Yatırım'dan dene
        if self.is_available:
            data = self._get_stock_data_isyatirim(
                symbol,
                start_date=datetime.now() - timedelta(days=5),
                end_date=datetime.now()
            )
            
            if data is not None and not data.empty:
                # Kapanış fiyatı sütununu bul
                price_col = None
                for col in ['HISSE_KAPANIS', 'Close', 'close', 'Kapanış']:
                    if col in data.columns:
                        price_col = col
                        break
                
                if price_col:
                    price = float(data[price_col].iloc[-1])
                    self.cache.set(cache_key, price)
                    return price
        
        # yfinance fallback
        if self.use_yfinance_fallback:
            try:
                clean_symbol = self._format_symbol_for_isyatirim(symbol)
                ticker_symbol = f"{clean_symbol}.IS"
                
                ticker = yf.Ticker(ticker_symbol)
                data = ticker.history(period="1d")
                
                if not data.empty:
                    price = float(data['Close'].iloc[-1])
                    if price > 0:
                        self.cache.set(cache_key, price)
                        return price
                        
            except Exception as e:
                logger.debug(f"yfinance hatası ({symbol}): {e}")
        
        return None
    
    def get_stock_price(self, symbol: str) -> Optional[float]:
        """get_current_price için alias"""
        return self.get_current_price(symbol)
    
    def get_historical_data(
        self, 
        symbol: str, 
        days: int = DEFAULT_DAYS
    ) -> Optional[pd.DataFrame]:
        """
        Tek hisse için geçmiş veriler
        
        Args:
            symbol: Hisse sembolü
            days: Gün sayısı
            
        Returns:
            DataFrame veya None
        """
        cache_key = f"hist_{symbol}_{days}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        
        # İş Yatırım'dan dene
        if self.is_available:
            try:
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days + 10)  # Buffer
                
                data = self._get_stock_data_isyatirim(symbol, start_date, end_date)
                
                # DataFrame kontrolü düzeltmesi
                if data is not None and not data.empty:
                    # Son N günü al
                    data = data.tail(days)
                    self.cache.set(cache_key, data)
                    return data
            except Exception as e:
                logger.debug(f"İş Yatırım geçmiş veri hatası: {e}")
        
        # yfinance fallback
        if self.use_yfinance_fallback:
            try:
                clean_symbol = self._format_symbol_for_isyatirim(symbol)
                ticker_symbol = f"{clean_symbol}.IS"
                
                ticker = yf.Ticker(ticker_symbol)
                data = ticker.history(period=f"{days}d")
                
                # DataFrame kontrolü düzeltmesi
                if data is not None and not data.empty:
                    self.cache.set(cache_key, data)
                    return data
                    
            except Exception as e:
                logger.debug(f"yfinance history hatası ({symbol}): {e}")
        
        return None
    
    def get_bist100_data(self, days: int = DEFAULT_DAYS) -> Optional[pd.DataFrame]:
        """
        BIST100 endeks verilerini al
        
        Args:
            days: Gün sayısı
            
        Returns:
            DataFrame veya None
        """
        # XU100 verisi al
        data = self.get_historical_data("XU100", days)
        
        # DataFrame kontrolü düzeltmesi
        if data is not None and not data.empty:
            return data
        
        # yfinance fallback
        if self.use_yfinance_fallback:
            try:
                ticker = yf.Ticker("XU100.IS")
                hist = ticker.history(period=f"{days}d")
                
                if hist is not None and not hist.empty:
                    return hist
            except Exception as e:
                logger.debug(f"BIST100 yfinance hatası: {e}")
        
        return None
    
    def get_index_data(self, callback: Optional[Callable] = None) -> List[Dict]:
        """
        Endeks verilerini al (async)
        
        Args:
            callback: Veri hazır olunca çağrılacak fonksiyon
            
        Returns:
            Boş liste (veri async olarak callback'e gönderilir)
        """
        def fetch():
            indices_data = []
            
            try:
                for name, symbol in INDICES.items():
                    try:
                        # BIST endeksleri için özel işlem
                        if symbol.startswith("XU"):
                            # İş Yatırım'dan çek
                            hist = self.get_historical_data(symbol.replace('.IS', ''), days=5)
                        else:
                            # yfinance'den çek
                            if self.use_yfinance_fallback:
                                ticker = yf.Ticker(symbol)
                                hist = ticker.history(period="5d")
                            else:
                                continue
                        
                        # DataFrame kontrolü düzeltmesi
                        if hist is not None and not hist.empty:
                            # Kapanış fiyatı sütunu
                            close_col = None
                            for col in ['Close', 'HISSE_KAPANIS', 'close', 'Kapanış']:
                                if col in hist.columns:
                                    close_col = col
                                    break
                            
                            if close_col:
                                last_price = float(hist[close_col].iloc[-1])
                                prev_price = float(hist[close_col].iloc[-2]) if len(hist) > 1 else last_price
                                daily_change = ((last_price - prev_price) / prev_price) * 100 if prev_price else 0
                                
                                indices_data.append({
                                    "name": name,
                                    "value": last_price,
                                    "change": daily_change,
                                    "history": hist[close_col].values.tolist()
                                })
                                
                    except Exception as e:
                        logger.debug(f"Endeks hatası ({name}): {e}")
                
                if callback:
                    callback(indices_data)
                    
            except Exception as e:
                logger.error(f"Endeks veri çekme hatası: {e}")
                if callback:
                    callback([])
            
            return indices_data
        
        # Arka planda çalıştır
        thread = threading.Thread(target=fetch, daemon=True)
        thread.start()
        return []
    
    def get_stock_history(self, symbol: str, period: str = "1y") -> Optional[pd.DataFrame]:
        """
        Hisse geçmişi al (period formatında)
        
        Args:
            symbol: Hisse sembolü
            period: '1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max'
            
        Returns:
            DataFrame veya None
        """
        # Period'u gün sayısına çevir
        period_map = {
            '1d': 1, '5d': 5, '1mo': 30, '3mo': 90,
            '6mo': 180, '1y': 365, '2y': 730, '5y': 1825,
            '10y': 3650, 'ytd': (datetime.now() - datetime(datetime.now().year, 1, 1)).days,
            'max': 3650
        }
        
        days = period_map.get(period, 365)
        return self.get_historical_data(symbol, days)
    
    # ========================================================================
    # MULTIPLE STOCKS METHODS
    # ========================================================================
    
    def get_multiple_prices(
        self, 
        symbols: List[str]
    ) -> Dict[str, Optional[float]]:
        """
        Birden fazla hisse için güncel fiyatlar
        
        Args:
            symbols: Hisse sembolleri listesi
            
        Returns:
            {symbol: price} sözlüğü
        """
        results = {}
        
        # Önce cache'e bak
        uncached = []
        for symbol in symbols:
            cache_key = f"price_{symbol}"
            cached = self.cache.get(cache_key)
            if cached is not None:
                results[symbol] = cached
            else:
                uncached.append(symbol)
        
        if not uncached:
            return results
        
        # İş Yatırım'dan toplu çekmeyi dene
        if self.is_available and uncached:
            try:
                # Sembolleri temizle
                clean_symbols = [self._format_symbol_for_isyatirim(s) for s in uncached]
                
                # Toplu veri çek
                end_date = datetime.now()
                start_date = end_date - timedelta(days=5)
                
                def _fetch():
                    return self._stock_data.get_data(
                        symbols=clean_symbols,  # Liste olarak gönder
                        start_date=start_date.strftime('%d-%m-%Y'),
                        end_date=end_date.strftime('%d-%m-%Y')
                    )
                
                data = self._safe_request(_fetch)
                
                if data is not None and not data.empty:
                    # Veri formatını kontrol et
                    if 'HISSE_KODU' in data.columns:
                        # Çoklu veri formatı
                        for i, symbol in enumerate(uncached):
                            clean_symbol = clean_symbols[i]
                            symbol_data = data[data['HISSE_KODU'] == clean_symbol]
                            
                            if not symbol_data.empty:
                                price_col = None
                                for col in ['HISSE_KAPANIS', 'Close']:
                                    if col in symbol_data.columns:
                                        price_col = col
                                        break
                                
                                if price_col:
                                    price = float(symbol_data[price_col].iloc[-1])
                                    results[symbol] = price
                                    self.cache.set(f"price_{symbol}", price)
                                else:
                                    results[symbol] = None
                            else:
                                results[symbol] = None
                    else:
                        # Tek sembol verisi (ilk sembol için)
                        if len(uncached) == 1:
                            price_col = None
                            for col in ['HISSE_KAPANIS', 'Close']:
                                if col in data.columns:
                                    price_col = col
                                    break
                            
                            if price_col:
                                price = float(data[price_col].iloc[-1])
                                results[uncached[0]] = price
                                self.cache.set(f"price_{uncached[0]}", price)
                
            except Exception as e:
                logger.error(f"Çoklu fiyat hatası: {e}")
        
        # Başarısız olanları tek tek dene
        for symbol in uncached:
            if symbol not in results or results[symbol] is None:
                results[symbol] = self.get_current_price(symbol)
        
        return results
    
    def get_multiple_historical_data(
        self, 
        symbols: List[str], 
        days: int = DEFAULT_DAYS
    ) -> Dict[str, pd.DataFrame]:
        """
        Birden fazla hisse için geçmiş veriler
        
        Args:
            symbols: Hisse sembolleri listesi
            days: Gün sayısı
            
        Returns:
            {symbol: DataFrame} sözlüğü
        """
        results = {}
        
        # Cache kontrolü
        uncached = []
        for symbol in symbols:
            cache_key = f"hist_{symbol}_{days}"
            cached = self.cache.get(cache_key)
            if cached is not None:
                results[symbol] = cached
            else:
                uncached.append(symbol)
        
        if not uncached:
            return results
        
        # İş Yatırım'dan toplu çekmeyi dene
        if self.is_available and uncached:
            try:
                clean_symbols = [self._format_symbol_for_isyatirim(s) for s in uncached]
                
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days + 10)
                
                def _fetch():
                    return self._stock_data.get_data(
                        symbols=clean_symbols,
                        start_date=start_date.strftime('%d-%m-%Y'),
                        end_date=end_date.strftime('%d-%m-%Y')
                    )
                
                data = self._safe_request(_fetch)
                
                if data is not None and not data.empty:
                    # Veri formatını kontrol et
                    if 'HISSE_KODU' in data.columns:
                        # Her sembol için ayır
                        for i, symbol in enumerate(uncached):
                            clean_symbol = clean_symbols[i]
                            symbol_data = data[data['HISSE_KODU'] == clean_symbol].copy()
                            
                            if not symbol_data.empty:
                                if not isinstance(symbol_data.index, pd.DatetimeIndex):
                                    symbol_data.index = pd.to_datetime(symbol_data.index)
                                symbol_data = symbol_data.tail(days)
                                results[symbol] = symbol_data
                                self.cache.set(f"hist_{symbol}_{days}", symbol_data)
                    else:
                        # Tek sembol verisi
                        if len(uncached) == 1:
                            if not isinstance(data.index, pd.DatetimeIndex):
                                data.index = pd.to_datetime(data.index)
                            data = data.tail(days)
                            results[uncached[0]] = data
                            self.cache.set(f"hist_{uncached[0]}_{days}", data)
                
            except Exception as e:
                logger.error(f"Çoklu geçmiş veri hatası: {e}")
        
        # Başarısız olanları tek tek çek
        for symbol in uncached:
            if symbol not in results:
                hist_data = self.get_historical_data(symbol, days)
                if hist_data is not None:
                    results[symbol] = hist_data
        
        return results
    
    # ========================================================================
    # CALCULATION METHODS
    # ========================================================================
    
    def calculate_returns(
        self, 
        symbol: str, 
        days: int = DEFAULT_DAYS
    ) -> Optional[np.ndarray]:
        """
        Günlük getirileri hesapla
        
        Args:
            symbol: Hisse sembolü
            days: Gün sayısı
            
        Returns:
            Getiri array'i veya None
        """
        df = self.get_historical_data(symbol, days)
        
        if df is None or df.empty:
            return None
        
        try:
            # Kapanış fiyatı sütununu bul
            price_col = None
            for col in ['HISSE_KAPANIS', 'Close', 'close', 'Kapanış']:
                if col in df.columns:
                    price_col = col
                    break
            
            if price_col is None:
                return None
            
            prices = df[price_col].values
            
            if len(prices) < 2:
                return None
            
            # Logaritmik getiri
            returns = np.diff(np.log(prices))
            
            return returns
            
        except Exception as e:
            logger.error(f"Getiri hesaplama hatası ({symbol}): {e}")
            return None
    
    def calculate_volatility(
        self, 
        symbol: str, 
        days: int = DEFAULT_DAYS
    ) -> Optional[float]:
        """
        Volatilite hesapla (yıllık)
        
        Args:
            symbol: Hisse sembolü
            days: Gün sayısı
            
        Returns:
            Yıllık volatilite % veya None
        """
        returns = self.calculate_returns(symbol, days)
        
        if returns is None or len(returns) < 2:
            return None
        
        try:
            daily_vol = np.std(returns)
            annual_vol = daily_vol * np.sqrt(TRADING_DAYS_PER_YEAR)
            return float(annual_vol * 100)
        except Exception as e:
            logger.error(f"Volatilite hesaplama hatası ({symbol}): {e}")
            return None
    
    # ========================================================================
    # MARKET DATA
    # ========================================================================
    
    def get_bist100_data(self, days: int = DEFAULT_DAYS) -> Optional[pd.DataFrame]:
        """
        BIST100 endeks verilerini al
        
        Args:
            days: Gün sayısı
            
        Returns:
            DataFrame veya None
        """
        return self.get_historical_data("XU100", days)
    
    def get_index_data(self, callback: Optional[Callable] = None) -> List[Dict]:
        """
        Endeks verilerini al
        
        Args:
            callback: Veri hazır olunca çağrılacak fonksiyon
            
        Returns:
            Endeks verileri listesi
        """
        def fetch():
            indices_data = []
            
            for name, symbol in INDICES.items():
                try:
                    # BIST endeksleri için özel işlem
                    if symbol.startswith("XU"):
                        # İş Yatırım'dan çek
                        hist = self.get_historical_data(symbol.replace('.IS', ''), days=5)
                    else:
                        # yfinance'den çek
                        if self.use_yfinance_fallback:
                            ticker = yf.Ticker(symbol)
                            hist = ticker.history(period="5d")
                        else:
                            continue
                    
                    if hist is not None and not hist.empty:
                        # Kapanış fiyatı sütunu
                        close_col = 'Close' if 'Close' in hist.columns else 'HISSE_KAPANIS'
                        
                        if close_col in hist.columns:
                            last_price = hist[close_col].iloc[-1]
                            prev_price = hist[close_col].iloc[-2] if len(hist) > 1 else last_price
                            daily_change = ((last_price - prev_price) / prev_price) * 100 if prev_price else 0
                            
                            indices_data.append({
                                "name": name,
                                "value": last_price,
                                "change": daily_change,
                                "history": hist[close_col].values.tolist()
                            })
                            
                except Exception as e:
                    logger.debug(f"Endeks hatası ({name}): {e}")
            
            if callback:
                callback(indices_data)
            return indices_data
        
        # Arka planda çalıştır
        thread = threading.Thread(target=fetch, daemon=True)
        thread.start()
        return []
    
    def get_currency_data(self, callback: Optional[Callable] = None) -> List[Dict]:
        """
        Döviz/altın verilerini al
        
        Args:
            callback: Veri hazır olunca çağrılacak fonksiyon
            
        Returns:
            Döviz verileri listesi
        """
        def fetch():
            currency_data = []
            
            if not self.use_yfinance_fallback:
                if callback:
                    callback([])
                return []
            
            # USD/TRY kurunu güncelle
            try:
                usd_try_ticker = yf.Ticker("TRY=X")
                usd_try_hist = usd_try_ticker.history(period="2d")
                if not usd_try_hist.empty:
                    self.usd_try_rate = usd_try_hist['Close'].iloc[-1]
            except:
                self.usd_try_rate = 34.50
            
            for name, symbol in CURRENCIES.items():
                try:
                    ticker = yf.Ticker(symbol)
                    hist = ticker.history(period="2d")
                    
                    if not hist.empty:
                        last_price = hist['Close'].iloc[-1]
                        prev_price = hist['Close'].iloc[-2] if len(hist) > 1 else last_price
                        daily_change = ((last_price - prev_price) / prev_price) * 100 if prev_price else 0
                        
                        # Formatla
                        if name == "BTC":
                            value_text = f"${last_price:,.0f}"
                            subtitle_text = f"₺{last_price * self.usd_try_rate:,.0f}"
                        elif name == "ALTIN":
                            value_text = f"${last_price:,.2f}"
                            subtitle_text = f"₺{last_price * self.usd_try_rate:,.2f}"
                        elif name in ["DOLAR", "EURO"]:
                            value_text = f"₺{last_price:.4f}"
                            subtitle_text = f"{daily_change:+.2f}%"
                        else:
                            value_text = f"{last_price:.2f}"
                            subtitle_text = f"{daily_change:+.2f}%"
                        
                        currency_data.append({
                            "name": name,
                            "value": last_price,
                            "value_text": value_text,
                            "change": daily_change,
                            "symbol": symbol,
                            "subtitle": subtitle_text
                        })
                        
                except Exception as e:
                    logger.debug(f"Döviz hatası ({name}): {e}")
            
            if callback:
                callback(currency_data)
            return currency_data
        
        thread = threading.Thread(target=fetch, daemon=True)
        thread.start()
        return []
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def update_all_prices(self, symbols: List[str]) -> Dict[str, Optional[float]]:
        """
        Tüm sembollerin fiyatlarını güncelle ve cache'i yenile
        
        Args:
            symbols: Sembol listesi
            
        Returns:
            Güncel fiyatlar
        """
        # Cache'i temizle
        for symbol in symbols:
            self.cache.remove_pattern(f"price_{symbol}")
        
        # Yeni fiyatları çek
        return self.get_multiple_prices(symbols)
    
    def clear_cache(self) -> None:
        """Tüm cache'i temizle"""
        self.cache.clear()
        logger.info("🗑️ Cache temizlendi")
    
    def is_market_open(self) -> bool:
        """Borsa açık mı?"""
        now = datetime.now()
        weekday = now.weekday()
        
        # Hafta sonu değilse
        if weekday < 5:  # Pazartesi-Cuma
            current_time = now.time()
            market_open = datetime.strptime("10:00", "%H:%M").time()
            market_close = datetime.strptime("18:00", "%H:%M").time()
            
            return market_open <= current_time <= market_close
        
        return False
    
    def get_last_trading_day(self) -> datetime:
        """Son işlem gününü döndür"""
        today = datetime.now()
        
        # Eğer bugün hafta sonuysa veya saat 18:00'den sonraysa
        if today.weekday() >= 5 or today.hour >= 18:
            # Cuma'yı bul
            days_since_friday = (today.weekday() - 4) % 7
            if days_since_friday == 0 and today.hour < 18:
                return today
            return today - timedelta(days=days_since_friday if days_since_friday > 0 else 7)
        
        return today
    
    def get_provider_info(self) -> Dict[str, Any]:
        """Sağlayıcı bilgisi"""
        return {
            'current_provider': self.provider,
            'is_yatirim_available': IS_YATIRIM_AVAILABLE,
            'yfinance_available': YFINANCE_AVAILABLE,
            'cache_size': len(self.cache._cache),
            'usd_try_rate': self.usd_try_rate,
            'market_open': self.is_market_open(),
            'last_trading_day': self.get_last_trading_day().strftime('%Y-%m-%d')
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

# Global singleton instance
api_service = APIService()