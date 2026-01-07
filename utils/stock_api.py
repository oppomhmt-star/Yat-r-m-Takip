# utils/stock_api.py

"""
İş Yatırım Hisse API Wrapper
isyatirimhisse kütüphanesi kullanarak Borsa İstanbul verilerini çeker
"""

from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import threading
from functools import lru_cache
import pandas as pd

try:
    from isyatirimhisse import StockData, Veri
    IS_YATIRIM_AVAILABLE = True
except ImportError:
    IS_YATIRIM_AVAILABLE = False
    print("⚠️ isyatirimhisse kütüphanesi bulunamadı. Yüklemek için: pip install isyatirimhisse")


@dataclass
class StockInfo:
    """Hisse bilgisi veri sınıfı"""
    symbol: str
    name: str
    current_price: float
    change_percent: float
    volume: int
    high: float
    low: float
    open_price: float
    previous_close: float
    timestamp: datetime


@dataclass  
class HistoricalData:
    """Geçmiş veri sınıfı"""
    dates: List[datetime]
    open_prices: List[float]
    high_prices: List[float]
    low_prices: List[float]
    close_prices: List[float]
    volumes: List[int]
    
    def to_dataframe(self) -> pd.DataFrame:
        """Pandas DataFrame'e dönüştür"""
        return pd.DataFrame({
            'Date': self.dates,
            'Open': self.open_prices,
            'High': self.high_prices,
            'Low': self.low_prices,
            'Close': self.close_prices,
            'Volume': self.volumes
        }).set_index('Date')


class IsYatirimAPI:
    """
    İş Yatırım Hisse API
    
    Borsa İstanbul hisse verilerini isyatirimhisse kütüphanesi ile çeker.
    Thread-safe ve cache destekli.
    """
    
    def __init__(self, cache_timeout: int = 300):
        """
        Args:
            cache_timeout: Cache süresi (saniye). Varsayılan 5 dakika.
        """
        self._cache_timeout = cache_timeout
        self._cache: Dict[str, Tuple[Any, datetime]] = {}
        self._lock = threading.Lock()
        
        if not IS_YATIRIM_AVAILABLE:
            raise ImportError("isyatirimhisse kütüphanesi yüklü değil!")
        
        self._stock_data = StockData()
    
    def _get_from_cache(self, key: str) -> Optional[Any]:
        """Cache'den veri al"""
        with self._lock:
            if key in self._cache:
                data, timestamp = self._cache[key]
                if (datetime.now() - timestamp).seconds < self._cache_timeout:
                    return data
                del self._cache[key]
        return None
    
    def _set_cache(self, key: str, data: Any) -> None:
        """Cache'e veri kaydet"""
        with self._lock:
            self._cache[key] = (data, datetime.now())
    
    def clear_cache(self) -> None:
        """Cache'i temizle"""
        with self._lock:
            self._cache.clear()
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Hissenin güncel fiyatını al
        
        Args:
            symbol: Hisse sembolü (örn: "THYAO")
            
        Returns:
            Güncel fiyat veya None
        """
        cache_key = f"price_{symbol}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        
        try:
            # isyatirimhisse ile güncel fiyat al
            data = self._stock_data.get_data(
                symbols=symbol,
                start_date=(datetime.now() - timedelta(days=5)).strftime('%d-%m-%Y'),
                end_date=datetime.now().strftime('%d-%m-%Y')
            )
            
            if data is not None and not data.empty:
                price = float(data['HISSE_KAPANIS'].iloc[-1])
                self._set_cache(cache_key, price)
                return price
                
        except Exception as e:
            print(f"Fiyat alma hatası ({symbol}): {e}")
        
        return None
    
    def get_stock_info(self, symbol: str) -> Optional[StockInfo]:
        """
        Hisse detaylı bilgilerini al
        
        Args:
            symbol: Hisse sembolü
            
        Returns:
            StockInfo objesi veya None
        """
        cache_key = f"info_{symbol}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=5)
            
            data = self._stock_data.get_data(
                symbols=symbol,
                start_date=start_date.strftime('%d-%m-%Y'),
                end_date=end_date.strftime('%d-%m-%Y')
            )
            
            if data is not None and not data.empty:
                latest = data.iloc[-1]
                previous = data.iloc[-2] if len(data) > 1 else latest
                
                current_price = float(latest['HISSE_KAPANIS'])
                prev_close = float(previous['HISSE_KAPANIS'])
                change_pct = ((current_price - prev_close) / prev_close) * 100
                
                info = StockInfo(
                    symbol=symbol,
                    name=symbol,  # İsim için ayrı API gerekebilir
                    current_price=current_price,
                    change_percent=change_pct,
                    volume=int(latest.get('HISSE_HACIM', 0)),
                    high=float(latest.get('HISSE_YUKSEK', current_price)),
                    low=float(latest.get('HISSE_DUSUK', current_price)),
                    open_price=float(latest.get('HISSE_ACILIS', current_price)),
                    previous_close=prev_close,
                    timestamp=datetime.now()
                )
                
                self._set_cache(cache_key, info)
                return info
                
        except Exception as e:
            print(f"Hisse bilgisi alma hatası ({symbol}): {e}")
        
        return None
    
    def get_historical_data(
        self, 
        symbol: str, 
        days: int = 365
    ) -> Optional[HistoricalData]:
        """
        Geçmiş fiyat verilerini al
        
        Args:
            symbol: Hisse sembolü
            days: Kaç günlük veri (varsayılan 1 yıl)
            
        Returns:
            HistoricalData objesi veya None
        """
        cache_key = f"history_{symbol}_{days}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            data = self._stock_data.get_data(
                symbols=symbol,
                start_date=start_date.strftime('%d-%m-%Y'),
                end_date=end_date.strftime('%d-%m-%Y')
            )
            
            if data is not None and not data.empty:
                historical = HistoricalData(
                    dates=[datetime.strptime(str(d)[:10], '%Y-%m-%d') for d in data.index],
                    open_prices=data.get('HISSE_ACILIS', data['HISSE_KAPANIS']).tolist(),
                    high_prices=data.get('HISSE_YUKSEK', data['HISSE_KAPANIS']).tolist(),
                    low_prices=data.get('HISSE_DUSUK', data['HISSE_KAPANIS']).tolist(),
                    close_prices=data['HISSE_KAPANIS'].tolist(),
                    volumes=data.get('HISSE_HACIM', pd.Series([0]*len(data))).astype(int).tolist()
                )
                
                self._set_cache(cache_key, historical)
                return historical
                
        except Exception as e:
            print(f"Geçmiş veri alma hatası ({symbol}): {e}")
        
        return None
    
    def get_multiple_prices(self, symbols: List[str]) -> Dict[str, Optional[float]]:
        """
        Birden fazla hissenin fiyatını al
        
        Args:
            symbols: Hisse sembolleri listesi
            
        Returns:
            {symbol: price} sözlüğü
        """
        results = {}
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=5)
            
            # Tüm sembolleri tek seferde çek
            data = self._stock_data.get_data(
                symbols=symbols,
                start_date=start_date.strftime('%d-%m-%Y'),
                end_date=end_date.strftime('%d-%m-%Y')
            )
            
            if data is not None and not data.empty:
                for symbol in symbols:
                    try:
                        symbol_data = data[data['HISSE_KODU'] == symbol]
                        if not symbol_data.empty:
                            results[symbol] = float(symbol_data['HISSE_KAPANIS'].iloc[-1])
                        else:
                            results[symbol] = None
                    except:
                        results[symbol] = None
            else:
                # Fallback: tek tek çek
                for symbol in symbols:
                    results[symbol] = self.get_current_price(symbol)
                    
        except Exception as e:
            print(f"Çoklu fiyat alma hatası: {e}")
            for symbol in symbols:
                results[symbol] = self.get_current_price(symbol)
        
        return results
    
    def get_bist100_data(self, days: int = 365) -> Optional[HistoricalData]:
        """
        BIST100 endeks verilerini al
        
        Args:
            days: Kaç günlük veri
            
        Returns:
            HistoricalData objesi veya None
        """
        return self.get_historical_data("XU100", days)
    
    def calculate_volatility(self, symbol: str, days: int = 30) -> Optional[float]:
        """
        Hisse volatilitesini hesapla (yıllık)
        
        Args:
            symbol: Hisse sembolü
            days: Hesaplama için kullanılacak gün sayısı
            
        Returns:
            Yıllık volatilite yüzdesi veya None
        """
        historical = self.get_historical_data(symbol, days + 10)  # Biraz fazla çek
        
        if historical is None or len(historical.close_prices) < 2:
            return None
        
        try:
            import numpy as np
            
            prices = np.array(historical.close_prices[-days:])
            returns = np.diff(np.log(prices))
            
            daily_vol = np.std(returns)
            annual_vol = daily_vol * np.sqrt(252)  # 252 işlem günü
            
            return float(annual_vol * 100)
            
        except Exception as e:
            print(f"Volatilite hesaplama hatası ({symbol}): {e}")
            return None


# Singleton instance
_api_instance: Optional[IsYatirimAPI] = None
_api_lock = threading.Lock()


def get_api() -> IsYatirimAPI:
    """Global API instance'ı al (Singleton)"""
    global _api_instance
    
    with _api_lock:
        if _api_instance is None:
            _api_instance = IsYatirimAPI()
        return _api_instance