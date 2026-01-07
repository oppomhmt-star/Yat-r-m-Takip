# utils/metrics.py

"""
Portföy Metrikleri Hesaplama Modülü

Bu modül portföy performans metriklerini hesaplar:
- Toplam getiri
- Volatilite
- Maksimum düşüş (drawdown)
- Sharpe oranı
- Çeşitlendirme skoru
- Dönemsel getiriler

isyatirimhisse kütüphanesi ile Borsa İstanbul verilerini kullanır.
"""

from __future__ import annotations

import threading
from typing import (
    TYPE_CHECKING, 
    Optional, 
    List, 
    Dict, 
    Any, 
    Tuple,
    Callable,
    Union
)
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from enum import Enum
import warnings

import numpy as np
import pandas as pd

# isyatirimhisse import
try:
    from isyatirimhisse import StockData
    IS_YATIRIM_AVAILABLE = True
except ImportError:
    IS_YATIRIM_AVAILABLE = False
    warnings.warn(
        "isyatirimhisse kütüphanesi bulunamadı. "
        "Yüklemek için: pip install isyatirimhisse",
        ImportWarning
    )

# Type checking imports
if TYPE_CHECKING:
    from numpy.typing import NDArray


# ============================================================================
# CONSTANTS
# ============================================================================

# Yıllık işlem günü sayısı (Borsa İstanbul)
TRADING_DAYS_PER_YEAR: int = 252

# Varsayılan risksiz faiz oranı (TCMB politika faizi yaklaşık)
DEFAULT_RISK_FREE_RATE: float = 0.45  # %45 yıllık

# Cache süresi (saniye)
CACHE_TIMEOUT: int = 300  # 5 dakika

# Varsayılan değerler
DEFAULT_VOLATILITY: float = 25.0
DEFAULT_SHARPE: float = 0.0
DEFAULT_DRAWDOWN: float = 5.0
DEFAULT_DIVERSIFICATION: float = 50.0


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass(frozen=True)
class StockReturn:
    """Hisse getiri verisi"""
    symbol: str
    returns: Tuple[float, ...]  # Immutable için tuple
    weight: float
    
    @property
    def returns_array(self) -> np.ndarray:
        """Numpy array olarak getiriler"""
        return np.array(self.returns)


@dataclass
class PortfolioComposition:
    """Portföy bileşeni"""
    symbol: str
    shares: int
    avg_cost: float
    current_price: float
    value: float
    weight: float
    profit_loss: float
    profit_loss_pct: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Dictionary'e dönüştür"""
        return {
            'symbol': self.symbol,
            'shares': self.shares,
            'avg_cost': self.avg_cost,
            'current_price': self.current_price,
            'value': self.value,
            'weight': self.weight,
            'profit_loss': self.profit_loss,
            'profit_loss_pct': self.profit_loss_pct
        }


@dataclass
class MetricsSummary:
    """Tüm metrikler özeti"""
    total_return: float
    volatility: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    diversification_score: float
    total_value: float
    total_cost: float
    profit_loss: float
    
    def to_dict(self) -> Dict[str, float]:
        """Dictionary'e dönüştür"""
        return {
            'total_return': self.total_return,
            'volatility': self.volatility,
            'max_drawdown': self.max_drawdown,
            'sharpe_ratio': self.sharpe_ratio,
            'sortino_ratio': self.sortino_ratio,
            'diversification_score': self.diversification_score,
            'total_value': self.total_value,
            'total_cost': self.total_cost,
            'profit_loss': self.profit_loss
        }


# ============================================================================
# CACHE MANAGER
# ============================================================================

class CacheManager:
    """Thread-safe cache yöneticisi"""
    
    def __init__(self, timeout: int = CACHE_TIMEOUT):
        self._cache: Dict[str, Tuple[Any, datetime]] = {}
        self._lock = threading.RLock()
        self._timeout = timeout
    
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
    
    def clear(self) -> None:
        """Cache'i temizle"""
        with self._lock:
            self._cache.clear()
    
    def remove(self, key: str) -> None:
        """Belirli bir anahtarı sil"""
        with self._lock:
            self._cache.pop(key, None)


# Global cache instance
_cache = CacheManager()


# ============================================================================
# STOCK DATA PROVIDER
# ============================================================================

class StockDataProvider:
    """
    Hisse senedi veri sağlayıcı
    
    isyatirimhisse kütüphanesi ile Borsa İstanbul verilerini çeker.
    Thread-safe ve cache destekli.
    """
    
    _instance: Optional['StockDataProvider'] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> 'StockDataProvider':
        """Singleton pattern"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._stock_data: Optional[StockData] = None
        self._data_lock = threading.RLock()
        
        if IS_YATIRIM_AVAILABLE:
            try:
                self._stock_data = StockData()
            except Exception as e:
                warnings.warn(f"StockData başlatılamadı: {e}")
        
        self._initialized = True
    
    @property
    def is_available(self) -> bool:
        """API kullanılabilir mi?"""
        return self._stock_data is not None
    
    def get_historical_data(
        self, 
        symbol: str, 
        days: int = 30
    ) -> Optional[pd.DataFrame]:
        """
        Geçmiş fiyat verilerini al
        
        Args:
            symbol: Hisse sembolü (örn: "THYAO")
            days: Kaç günlük veri
            
        Returns:
            DataFrame veya None
        """
        cache_key = f"hist_{symbol}_{days}"
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached
        
        if not self.is_available:
            return None
        
        with self._data_lock:
            try:
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days + 10)  # Hafta sonları için buffer
                
                data = self._stock_data.get_data(
                    symbols=symbol,
                    start_date=start_date.strftime('%d-%m-%Y'),
                    end_date=end_date.strftime('%d-%m-%Y')
                )
                
                if data is not None and not data.empty:
                    # Veriyi düzenle
                    df = data.copy()
                    
                    # Index'i datetime yap
                    if not isinstance(df.index, pd.DatetimeIndex):
                        df.index = pd.to_datetime(df.index)
                    
                    # Son N günü al
                    df = df.tail(days)
                    
                    _cache.set(cache_key, df)
                    return df
                    
            except Exception as e:
                print(f"Geçmiş veri hatası ({symbol}): {e}")
        
        return None
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Güncel fiyatı al
        
        Args:
            symbol: Hisse sembolü
            
        Returns:
            Güncel fiyat veya None
        """
        cache_key = f"price_{symbol}"
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached
        
        df = self.get_historical_data(symbol, days=5)
        
        if df is not None and not df.empty:
            try:
                # Kapanış fiyatı sütun adı
                close_col = None
                for col in ['HISSE_KAPANIS', 'Close', 'close', 'Kapanış']:
                    if col in df.columns:
                        close_col = col
                        break
                
                if close_col:
                    price = float(df[close_col].iloc[-1])
                    _cache.set(cache_key, price)
                    return price
                    
            except Exception as e:
                print(f"Fiyat okuma hatası ({symbol}): {e}")
        
        return None
    
    def get_multiple_historical_data(
        self, 
        symbols: List[str], 
        days: int = 30
    ) -> Dict[str, pd.DataFrame]:
        """
        Birden fazla hisse için geçmiş veri al
        
        Args:
            symbols: Hisse sembolleri listesi
            days: Kaç günlük veri
            
        Returns:
            {symbol: DataFrame} sözlüğü
        """
        results = {}
        
        # Önce cache'e bak
        uncached = []
        for symbol in symbols:
            cache_key = f"hist_{symbol}_{days}"
            cached = _cache.get(cache_key)
            if cached is not None:
                results[symbol] = cached
            else:
                uncached.append(symbol)
        
        if not uncached:
            return results
        
        # Cache'de olmayanları çek
        if self.is_available and uncached:
            with self._data_lock:
                try:
                    end_date = datetime.now()
                    start_date = end_date - timedelta(days=days + 10)
                    
                    # Toplu çekme denemesi
                    data = self._stock_data.get_data(
                        symbols=uncached,
                        start_date=start_date.strftime('%d-%m-%Y'),
                        end_date=end_date.strftime('%d-%m-%Y')
                    )
                    
                    if data is not None and not data.empty:
                        # Her sembol için ayır
                        if 'HISSE_KODU' in data.columns:
                            for symbol in uncached:
                                symbol_data = data[data['HISSE_KODU'] == symbol].copy()
                                if not symbol_data.empty:
                                    if not isinstance(symbol_data.index, pd.DatetimeIndex):
                                        symbol_data.index = pd.to_datetime(symbol_data.index)
                                    symbol_data = symbol_data.tail(days)
                                    
                                    results[symbol] = symbol_data
                                    _cache.set(f"hist_{symbol}_{days}", symbol_data)
                        else:
                            # Tek sembol döndü
                            if len(uncached) == 1:
                                symbol = uncached[0]
                                if not isinstance(data.index, pd.DatetimeIndex):
                                    data.index = pd.to_datetime(data.index)
                                data = data.tail(days)
                                
                                results[symbol] = data
                                _cache.set(f"hist_{symbol}_{days}", data)
                                
                except Exception as e:
                    print(f"Toplu veri çekme hatası: {e}")
        
        # Hala eksik olanları tek tek çek
        for symbol in uncached:
            if symbol not in results:
                df = self.get_historical_data(symbol, days)
                if df is not None:
                    results[symbol] = df
        
        return results
    
    def calculate_returns(
        self, 
        symbol: str, 
        days: int = 30
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
            close_col = None
            for col in ['HISSE_KAPANIS', 'Close', 'close', 'Kapanış']:
                if col in df.columns:
                    close_col = col
                    break
            
            if close_col is None:
                return None
            
            prices = df[close_col].values
            
            if len(prices) < 2:
                return None
            
            # Logaritmik getiri hesapla
            returns = np.diff(np.log(prices))
            
            return returns
            
        except Exception as e:
            print(f"Getiri hesaplama hatası ({symbol}): {e}")
            return None


# Global provider instance
def get_data_provider() -> StockDataProvider:
    """Global veri sağlayıcı instance'ı al"""
    return StockDataProvider()


# ============================================================================
# PORTFOLIO METRICS
# ============================================================================

class PortfolioMetrics:
    """
    Portföy Metrikleri Hesaplayıcı
    
    Bu sınıf portföy performansını ölçmek için çeşitli metrikler hesaplar:
    - Getiri metrikleri (toplam, dönemsel)
    - Risk metrikleri (volatilite, VaR, max drawdown)
    - Risk-ayarlı getiri (Sharpe, Sortino)
    - Çeşitlendirme analizi
    
    Attributes:
        portfolio: Portföy listesi [{sembol, adet, ort_maliyet, guncel_fiyat}, ...]
        transactions: İşlem geçmişi listesi
        
    Example:
        >>> portfolio = [
        ...     {'sembol': 'THYAO', 'adet': 100, 'ort_maliyet': 150.0, 'guncel_fiyat': 180.0},
        ...     {'sembol': 'SISE', 'adet': 200, 'ort_maliyet': 45.0, 'guncel_fiyat': 52.0}
        ... ]
        >>> metrics = PortfolioMetrics(portfolio)
        >>> print(f"Toplam Getiri: {metrics.calculate_total_return():.2f}%")
    """
    
    def __init__(
        self, 
        portfolio: Optional[List[Dict[str, Any]]] = None,
        transactions: Optional[List[Dict[str, Any]]] = None,
        data_provider: Optional[StockDataProvider] = None
    ):
        """
        Args:
            portfolio: Portföy listesi
            transactions: İşlem geçmişi
            data_provider: Veri sağlayıcı (None ise global kullanılır)
        """
        self.portfolio = portfolio or []
        self.transactions = transactions or []
        self._provider = data_provider or get_data_provider()
        
        # Hesaplama cache'leri
        self._total_value: Optional[float] = None
        self._total_cost: Optional[float] = None
        self._daily_returns_cache: Optional[List[StockReturn]] = None
        self._cache_days: Optional[int] = None
        
        # Thread safety
        self._lock = threading.RLock()
    
    # ========================================================================
    # PROPERTIES
    # ========================================================================
    
    @property
    def total_value(self) -> float:
        """Toplam portföy değeri"""
        if self._total_value is None:
            self._total_value = sum(
                stock['adet'] * stock.get('guncel_fiyat', stock['ort_maliyet'])
                for stock in self.portfolio
            )
        return self._total_value
    
    @property
    def total_cost(self) -> float:
        """Toplam maliyet"""
        if self._total_cost is None:
            self._total_cost = sum(
                stock['adet'] * stock['ort_maliyet']
                for stock in self.portfolio
            )
        return self._total_cost
    
    @property
    def profit_loss(self) -> float:
        """Toplam kar/zarar"""
        return self.total_value - self.total_cost
    
    @property
    def num_stocks(self) -> int:
        """Portföydeki hisse sayısı"""
        return len(self.portfolio)
    
    # ========================================================================
    # CACHE MANAGEMENT
    # ========================================================================
    
    def invalidate_cache(self) -> None:
        """Tüm cache'leri temizle"""
        with self._lock:
            self._total_value = None
            self._total_cost = None
            self._daily_returns_cache = None
            self._cache_days = None
    
    def update_prices(self) -> bool:
        """
        Güncel fiyatları güncelle
        
        Returns:
            Başarılı ise True
        """
        if not self.portfolio:
            return False
        
        updated = False
        
        for stock in self.portfolio:
            symbol = stock['sembol']
            price = self._provider.get_current_price(symbol)
            
            if price is not None:
                stock['guncel_fiyat'] = price
                updated = True
        
        if updated:
            self.invalidate_cache()
        
        return updated
    
    # ========================================================================
    # RETURN CALCULATIONS
    # ========================================================================
    
    def calculate_total_return(self) -> float:
        """
        Toplam getiri yüzdesini hesapla
        
        Returns:
            Getiri yüzdesi (örn: 15.5 = %15.5)
        """
        try:
            if self.total_cost == 0:
                return 0.0
            
            return ((self.total_value - self.total_cost) / self.total_cost) * 100
            
        except Exception as e:
            print(f"Toplam getiri hesaplama hatası: {e}")
            return 0.0
    
    def calculate_daily_returns(
        self, 
        days: int = 30,
        force_refresh: bool = False
    ) -> List[StockReturn]:
        """
        Tüm hisseler için günlük getirileri hesapla
        
        Args:
            days: Gün sayısı
            force_refresh: Cache'i yoksay
            
        Returns:
            StockReturn listesi
        """
        with self._lock:
            # Cache kontrolü
            if (not force_refresh 
                and self._daily_returns_cache is not None 
                and self._cache_days == days):
                return self._daily_returns_cache
            
            returns_list: List[StockReturn] = []
            
            if not self.portfolio:
                return returns_list
            
            try:
                # Tüm sembolleri çek
                symbols = [stock['sembol'] for stock in self.portfolio]
                all_data = self._provider.get_multiple_historical_data(symbols, days)
                
                for stock in self.portfolio:
                    symbol = stock['sembol']
                    
                    if symbol not in all_data:
                        continue
                    
                    df = all_data[symbol]
                    
                    if df.empty:
                        continue
                    
                    # Kapanış fiyatı sütununu bul
                    close_col = None
                    for col in ['HISSE_KAPANIS', 'Close', 'close', 'Kapanış']:
                        if col in df.columns:
                            close_col = col
                            break
                    
                    if close_col is None:
                        continue
                    
                    prices = df[close_col].values
                    
                    if len(prices) < 2:
                        continue
                    
                    # Logaritmik günlük getiri
                    daily_returns = np.diff(np.log(prices))
                    
                    # Ağırlık hesapla
                    value = stock['adet'] * stock.get('guncel_fiyat', stock['ort_maliyet'])
                    weight = value / self.total_value if self.total_value > 0 else 0
                    
                    returns_list.append(StockReturn(
                        symbol=symbol,
                        returns=tuple(daily_returns),
                        weight=weight
                    ))
                
                # Cache'e kaydet
                self._daily_returns_cache = returns_list
                self._cache_days = days
                
            except Exception as e:
                print(f"Günlük getiri hesaplama hatası: {e}")
            
            return returns_list
    
    def calculate_period_return(self, days: int) -> float:
        """
        Belirli bir dönemdeki getiriyi hesapla
        
        Args:
            days: Dönem (gün)
            
        Returns:
            Dönemsel getiri yüzdesi
        """
        if days <= 0 or not self.portfolio:
            return 0.0
        
        try:
            # Her hisse için dönem başı ve sonu fiyatlarını al
            total_start_value = 0.0
            total_end_value = 0.0
            
            symbols = [stock['sembol'] for stock in self.portfolio]
            all_data = self._provider.get_multiple_historical_data(symbols, days)
            
            for stock in self.portfolio:
                symbol = stock['sembol']
                shares = stock['adet']
                
                if symbol in all_data and not all_data[symbol].empty:
                    df = all_data[symbol]
                    
                    # Kapanış sütununu bul
                    close_col = None
                    for col in ['HISSE_KAPANIS', 'Close', 'close', 'Kapanış']:
                        if col in df.columns:
                            close_col = col
                            break
                    
                    if close_col and len(df) >= 2:
                        start_price = float(df[close_col].iloc[0])
                        end_price = float(df[close_col].iloc[-1])
                        
                        total_start_value += shares * start_price
                        total_end_value += shares * end_price
                else:
                    # Veri yoksa mevcut fiyatı kullan
                    current_price = stock.get('guncel_fiyat', stock['ort_maliyet'])
                    total_start_value += shares * current_price
                    total_end_value += shares * current_price
            
            if total_start_value == 0:
                return 0.0
            
            return ((total_end_value - total_start_value) / total_start_value) * 100
            
        except Exception as e:
            print(f"Dönem getirisi hesaplama hatası: {e}")
            
            # Fallback: toplam getiriyi oranla
            total_return = self.calculate_total_return()
            return (total_return / 365) * days
    
    # ========================================================================
    # RISK CALCULATIONS
    # ========================================================================
    
    def calculate_volatility(self, days: int = 30) -> float:
        """
        Portföy volatilitesini hesapla (yıllık)
        
        Args:
            days: Hesaplama dönemi
            
        Returns:
            Yıllık volatilite yüzdesi
        """
        try:
            daily_returns = self.calculate_daily_returns(days)
            
            if not daily_returns:
                return DEFAULT_VOLATILITY
            
            # Minimum veri uzunluğunu bul
            min_length = min(len(r.returns) for r in daily_returns)
            
            if min_length < 5:  # En az 5 gün veri gerekli
                return DEFAULT_VOLATILITY
            
            # Portföy getirilerini hesapla
            portfolio_returns = np.zeros(min_length)
            total_weight = sum(r.weight for r in daily_returns)
            
            if total_weight <= 0:
                return DEFAULT_VOLATILITY
            
            for stock_return in daily_returns:
                returns = stock_return.returns_array[-min_length:]
                weight = stock_return.weight / total_weight
                portfolio_returns += returns * weight
            
            # Günlük standart sapma
            daily_std = np.std(portfolio_returns, ddof=1)
            
            # Yıllık volatilite
            annual_volatility = daily_std * np.sqrt(TRADING_DAYS_PER_YEAR) * 100
            
            return float(annual_volatility)
            
        except Exception as e:
            print(f"Volatilite hesaplama hatası: {e}")
            return DEFAULT_VOLATILITY
    
    def calculate_downside_volatility(self, days: int = 30) -> float:
        """
        Negatif volatiliteyi hesapla (Sortino için)
        
        Args:
            days: Hesaplama dönemi
            
        Returns:
            Yıllık negatif volatilite
        """
        try:
            daily_returns = self.calculate_daily_returns(days)
            
            if not daily_returns:
                return DEFAULT_VOLATILITY
            
            # Minimum uzunluk
            min_length = min(len(r.returns) for r in daily_returns)
            
            if min_length < 5:
                return DEFAULT_VOLATILITY
            
            # Portföy getirilerini hesapla
            portfolio_returns = np.zeros(min_length)
            total_weight = sum(r.weight for r in daily_returns)
            
            if total_weight <= 0:
                return DEFAULT_VOLATILITY
            
            for stock_return in daily_returns:
                returns = stock_return.returns_array[-min_length:]
                weight = stock_return.weight / total_weight
                portfolio_returns += returns * weight
            
            # Sadece negatif getiriler
            negative_returns = portfolio_returns[portfolio_returns < 0]
            
            if len(negative_returns) < 2:
                return DEFAULT_VOLATILITY / 2  # Düşük risk
            
            downside_std = np.std(negative_returns, ddof=1)
            annual_downside = downside_std * np.sqrt(TRADING_DAYS_PER_YEAR) * 100
            
            return float(annual_downside)
            
        except Exception as e:
            print(f"Negatif volatilite hesaplama hatası: {e}")
            return DEFAULT_VOLATILITY
    
    def calculate_max_drawdown(self) -> float:
        """
        Maksimum düşüşü hesapla (drawdown)
        
        Portföyün en yüksek noktasından en düşük noktasına
        kadar yaşadığı en büyük düşüşü hesaplar.
        
        Returns:
            Maksimum düşüş yüzdesi (pozitif değer)
        """
        try:
            if not self.portfolio:
                return 0.0
            
            # Tarihsel portföy değerlerini hesapla
            symbols = [stock['sembol'] for stock in self.portfolio]
            all_data = self._provider.get_multiple_historical_data(symbols, days=90)
            
            if not all_data:
                # Fallback: mevcut maliyet-fiyat farkından hesapla
                return self._calculate_simple_drawdown()
            
            # Ortak tarihleri bul
            all_dates = set()
            data_by_symbol = {}
            
            for symbol, df in all_data.items():
                if df.empty:
                    continue
                    
                close_col = None
                for col in ['HISSE_KAPANIS', 'Close', 'close', 'Kapanış']:
                    if col in df.columns:
                        close_col = col
                        break
                
                if close_col:
                    data_by_symbol[symbol] = df[close_col].to_dict()
                    all_dates.update(df.index)
            
            if not all_dates or not data_by_symbol:
                return self._calculate_simple_drawdown()
            
            # Günlük portföy değerlerini hesapla
            sorted_dates = sorted(all_dates)
            portfolio_values = []
            
            for date in sorted_dates:
                daily_value = 0.0
                
                for stock in self.portfolio:
                    symbol = stock['sembol']
                    shares = stock['adet']
                    
                    if symbol in data_by_symbol:
                        # En yakın tarihi bul
                        price = None
                        for d in [date] + sorted_dates:
                            if d in data_by_symbol[symbol]:
                                price = data_by_symbol[symbol][d]
                                break
                        
                        if price is not None:
                            daily_value += shares * price
                        else:
                            daily_value += shares * stock.get('guncel_fiyat', stock['ort_maliyet'])
                    else:
                        daily_value += shares * stock.get('guncel_fiyat', stock['ort_maliyet'])
                
                if daily_value > 0:
                    portfolio_values.append(daily_value)
            
            if len(portfolio_values) < 2:
                return self._calculate_simple_drawdown()
            
            # Drawdown hesapla
            values = np.array(portfolio_values)
            peak = np.maximum.accumulate(values)
            drawdown = (peak - values) / peak * 100
            
            max_dd = float(np.max(drawdown))
            
            return max_dd
            
        except Exception as e:
            print(f"Max drawdown hesaplama hatası: {e}")
            return DEFAULT_DRAWDOWN
    
    def _calculate_simple_drawdown(self) -> float:
        """Basit drawdown hesaplama (fallback)"""
        max_dd = 0.0
        
        for stock in self.portfolio:
            current = stock.get('guncel_fiyat', stock['ort_maliyet'])
            cost = stock['ort_maliyet']
            
            if current < cost and cost > 0:
                dd = ((cost - current) / cost) * 100
                max_dd = max(max_dd, dd)
        
        return max_dd if max_dd > 0 else DEFAULT_DRAWDOWN
    
    def calculate_var(
        self, 
        confidence: float = 0.95, 
        days: int = 30
    ) -> float:
        """
        Value at Risk (VaR) hesapla
        
        Args:
            confidence: Güven düzeyi (örn: 0.95)
            days: Hesaplama dönemi
            
        Returns:
            VaR değeri (portföy yüzdesi)
        """
        try:
            daily_returns = self.calculate_daily_returns(days)
            
            if not daily_returns:
                return 5.0  # Varsayılan %5
            
            # Minimum uzunluk
            min_length = min(len(r.returns) for r in daily_returns)
            
            if min_length < 10:
                return 5.0
            
            # Portföy getirileri
            portfolio_returns = np.zeros(min_length)
            total_weight = sum(r.weight for r in daily_returns)
            
            if total_weight <= 0:
                return 5.0
            
            for stock_return in daily_returns:
                returns = stock_return.returns_array[-min_length:]
                weight = stock_return.weight / total_weight
                portfolio_returns += returns * weight
            
            # VaR = negatif percentile
            var = np.percentile(portfolio_returns, (1 - confidence) * 100)
            
            return abs(float(var)) * 100
            
        except Exception as e:
            print(f"VaR hesaplama hatası: {e}")
            return 5.0
    
    # ========================================================================
    # RISK-ADJUSTED RETURNS
    # ========================================================================
    
    def calculate_sharpe_ratio(
        self, 
        risk_free_rate: Optional[float] = None,
        days: int = 30
    ) -> float:
        """
        Sharpe Oranını hesapla
        
        Sharpe = (Portföy Getirisi - Risksiz Getiri) / Volatilite
        
        Args:
            risk_free_rate: Yıllık risksiz faiz oranı (None ise varsayılan)
            days: Hesaplama dönemi
            
        Returns:
            Sharpe oranı
        """
        try:
            if risk_free_rate is None:
                risk_free_rate = DEFAULT_RISK_FREE_RATE
            
            # Yıllık getiri tahmini
            period_return = self.calculate_period_return(days)
            annual_return = (period_return / days) * 365 if days > 0 else 0
            
            volatility = self.calculate_volatility(days)
            
            if volatility <= 0:
                return DEFAULT_SHARPE
            
            # Fazla getiri
            excess_return = annual_return - (risk_free_rate * 100)
            
            sharpe = excess_return / volatility
            
            return float(sharpe)
            
        except Exception as e:
            print(f"Sharpe oranı hesaplama hatası: {e}")
            return DEFAULT_SHARPE
    
    def calculate_sortino_ratio(
        self, 
        risk_free_rate: Optional[float] = None,
        days: int = 30
    ) -> float:
        """
        Sortino Oranını hesapla
        
        Sortino = (Portföy Getirisi - Risksiz Getiri) / Negatif Volatilite
        
        Args:
            risk_free_rate: Yıllık risksiz faiz oranı
            days: Hesaplama dönemi
            
        Returns:
            Sortino oranı
        """
        try:
            if risk_free_rate is None:
                risk_free_rate = DEFAULT_RISK_FREE_RATE
            
            period_return = self.calculate_period_return(days)
            annual_return = (period_return / days) * 365 if days > 0 else 0
            
            downside_vol = self.calculate_downside_volatility(days)
            
            if downside_vol <= 0:
                return 0.0
            
            excess_return = annual_return - (risk_free_rate * 100)
            sortino = excess_return / downside_vol
            
            return float(sortino)
            
        except Exception as e:
            print(f"Sortino oranı hesaplama hatası: {e}")
            return 0.0
    
    # ========================================================================
    # DIVERSIFICATION
    # ========================================================================
    
    def calculate_diversification_score(self) -> float:
        """
        Çeşitlendirme skorunu hesapla (0-100)
        
        Skor şu faktörlere göre hesaplanır:
        - Hisse sayısı (max 30 puan)
        - Sektör çeşitliliği (max 40 puan)
        - Konsantrasyon riski (max 30 puan)
        
        Returns:
            Diversifikasyon skoru (0-100)
        """
        if not self.portfolio:
            return 0.0
        
        score = 0.0
        
        # 1. Hisse sayısı puanı (max 30)
        num_stocks = len(self.portfolio)
        stock_score = min(num_stocks * 3, 30)
        score += stock_score
        
        # 2. Sektör çeşitliliği (max 40)
        sector_score = self._calculate_sector_diversity_score()
        score += sector_score
        
        # 3. Konsantrasyon riski (max 30)
        concentration_score = self._calculate_concentration_score()
        score += concentration_score
        
        return min(score, 100.0)
    
    def _calculate_sector_diversity_score(self) -> float:
        """Sektör çeşitliliği puanı"""
        try:
            from utils.sector_mapper import get_sector
            
            sectors = set()
            for stock in self.portfolio:
                sector = get_sector(stock['sembol'])
                sectors.add(sector)
            
            num_sectors = len(sectors)
            return min(num_sectors * 8, 40)
            
        except ImportError:
            # sector_mapper yoksa basit hesaplama
            num_stocks = len(self.portfolio)
            return min(num_stocks * 4, 40)
            
        except Exception as e:
            print(f"Sektör çeşitliliği hesaplama hatası: {e}")
            return 20.0
    
    def _calculate_concentration_score(self) -> float:
        """Konsantrasyon riski puanı"""
        try:
            if self.total_value <= 0:
                return 15.0
            
            # Her hissenin ağırlığını hesapla
            weights = []
            for stock in self.portfolio:
                value = stock['adet'] * stock.get('guncel_fiyat', stock['ort_maliyet'])
                weight = value / self.total_value
                weights.append(weight)
            
            weights.sort(reverse=True)
            
            # En büyük 3 hissenin ağırlığı
            top3_weight = sum(weights[:min(3, len(weights))])
            
            # HHI (Herfindahl-Hirschman Index)
            hhi = sum(w ** 2 for w in weights)
            
            # Puanlama
            if top3_weight <= 0.50:  # İyi dağılım
                concentration_score = 30
            elif top3_weight <= 0.70:  # Orta dağılım
                concentration_score = 20
            elif top3_weight <= 0.85:  # Zayıf dağılım
                concentration_score = 10
            else:  # Kötü dağılım
                concentration_score = 5
            
            return float(concentration_score)
            
        except Exception as e:
            print(f"Konsantrasyon hesaplama hatası: {e}")
            return 15.0
    
    def calculate_correlation_matrix(self, days: int = 90) -> Optional[pd.DataFrame]:
        """
        Hisseler arası korelasyon matrisini hesapla
        
        Args:
            days: Hesaplama dönemi
            
        Returns:
            Korelasyon matrisi DataFrame veya None
        """
        try:
            if len(self.portfolio) < 2:
                return None
            
            symbols = [stock['sembol'] for stock in self.portfolio]
            all_data = self._provider.get_multiple_historical_data(symbols, days)
            
            if len(all_data) < 2:
                return None
            
            # Getiri serileri oluştur
            returns_dict = {}
            
            for symbol, df in all_data.items():
                if df.empty:
                    continue
                
                close_col = None
                for col in ['HISSE_KAPANIS', 'Close', 'close', 'Kapanış']:
                    if col in df.columns:
                        close_col = col
                        break
                
                if close_col:
                    returns = df[close_col].pct_change().dropna()
                    returns_dict[symbol] = returns
            
            if len(returns_dict) < 2:
                return None
            
            # DataFrame oluştur ve korelasyon hesapla
            returns_df = pd.DataFrame(returns_dict)
            correlation = returns_df.corr()
            
            return correlation
            
        except Exception as e:
            print(f"Korelasyon matrisi hesaplama hatası: {e}")
            return None
    
    # ========================================================================
    # PORTFOLIO COMPOSITION
    # ========================================================================
    
    def get_portfolio_composition(self) -> List[PortfolioComposition]:
        """
        Portföy bileşimini detaylı olarak döndür
        
        Returns:
            PortfolioComposition listesi (değere göre sıralı)
        """
        composition = []
        
        for stock in self.portfolio:
            current_price = stock.get('guncel_fiyat', stock['ort_maliyet'])
            shares = stock['adet']
            avg_cost = stock['ort_maliyet']
            
            value = shares * current_price
            cost = shares * avg_cost
            profit_loss = value - cost
            profit_loss_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
            weight = (value / self.total_value * 100) if self.total_value > 0 else 0
            
            composition.append(PortfolioComposition(
                symbol=stock['sembol'],
                shares=shares,
                avg_cost=avg_cost,
                current_price=current_price,
                value=value,
                weight=weight,
                profit_loss=profit_loss,
                profit_loss_pct=profit_loss_pct
            ))
        
        # Değere göre sırala
        composition.sort(key=lambda x: x.value, reverse=True)
        
        return composition
    
    def get_summary(self, days: int = 30) -> MetricsSummary:
        """
        Tüm metriklerin özetini al
        
        Args:
            days: Hesaplama dönemi
            
        Returns:
            MetricsSummary objesi
        """
        return MetricsSummary(
            total_return=self.calculate_total_return(),
            volatility=self.calculate_volatility(days),
            max_drawdown=self.calculate_max_drawdown(),
            sharpe_ratio=self.calculate_sharpe_ratio(days=days),
            sortino_ratio=self.calculate_sortino_ratio(days=days),
            diversification_score=self.calculate_diversification_score(),
            total_value=self.total_value,
            total_cost=self.total_cost,
            profit_loss=self.profit_loss
        )
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def get_best_performers(self, n: int = 5) -> List[PortfolioComposition]:
        """En iyi performans gösteren N hisse"""
        composition = self.get_portfolio_composition()
        return sorted(composition, key=lambda x: x.profit_loss_pct, reverse=True)[:n]
    
    def get_worst_performers(self, n: int = 5) -> List[PortfolioComposition]:
        """En kötü performans gösteren N hisse"""
        composition = self.get_portfolio_composition()
        return sorted(composition, key=lambda x: x.profit_loss_pct)[:n]
    
    def get_weight_distribution(self) -> Dict[str, float]:
        """Hisse ağırlık dağılımı"""
        if self.total_value <= 0:
            return {}
        
        return {
            stock['sembol']: (stock['adet'] * stock.get('guncel_fiyat', stock['ort_maliyet'])) / self.total_value * 100
            for stock in self.portfolio
        }


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def create_metrics(
    portfolio: Optional[List[Dict[str, Any]]] = None,
    transactions: Optional[List[Dict[str, Any]]] = None
) -> PortfolioMetrics:
    """
    PortfolioMetrics factory fonksiyonu
    
    Args:
        portfolio: Portföy listesi
        transactions: İşlem geçmişi
        
    Returns:
        PortfolioMetrics instance
    """
    return PortfolioMetrics(portfolio, transactions)


# ============================================================================
# STANDALONE FUNCTIONS
# ============================================================================

def calculate_stock_volatility(symbol: str, days: int = 30) -> Optional[float]:
    """
    Tek bir hissenin volatilitesini hesapla
    
    Args:
        symbol: Hisse sembolü
        days: Gün sayısı
        
    Returns:
        Yıllık volatilite yüzdesi veya None
    """
    provider = get_data_provider()
    returns = provider.calculate_returns(symbol, days)
    
    if returns is None or len(returns) < 5:
        return None
    
    daily_std = np.std(returns, ddof=1)
    annual_vol = daily_std * np.sqrt(TRADING_DAYS_PER_YEAR) * 100
    
    return float(annual_vol)


def calculate_stock_beta(
    symbol: str, 
    benchmark: str = "XU100",
    days: int = 90
) -> Optional[float]:
    """
    Hissenin beta değerini hesapla
    
    Args:
        symbol: Hisse sembolü
        benchmark: Karşılaştırma endeksi
        days: Gün sayısı
        
    Returns:
        Beta değeri veya None
    """
    provider = get_data_provider()
    
    stock_returns = provider.calculate_returns(symbol, days)
    bench_returns = provider.calculate_returns(benchmark, days)
    
    if stock_returns is None or bench_returns is None:
        return None
    
    # Uzunlukları eşitle
    min_len = min(len(stock_returns), len(bench_returns))
    
    if min_len < 10:
        return None
    
    stock_returns = stock_returns[-min_len:]
    bench_returns = bench_returns[-min_len:]
    
    # Beta = Cov(stock, benchmark) / Var(benchmark)
    covariance = np.cov(stock_returns, bench_returns)[0, 1]
    variance = np.var(bench_returns, ddof=1)
    
    if variance == 0:
        return None
    
    beta = covariance / variance
    
    return float(beta)


# ============================================================================
# BACKWARDS COMPATIBILITY
# ============================================================================

# Eski API uyumluluğu için alias'lar
def calculate_total_return(portfolio: List[Dict]) -> float:
    """Geriye uyumluluk için wrapper"""
    metrics = PortfolioMetrics(portfolio)
    return metrics.calculate_total_return()


def calculate_volatility(portfolio: List[Dict], days: int = 30) -> float:
    """Geriye uyumluluk için wrapper"""
    metrics = PortfolioMetrics(portfolio)
    return metrics.calculate_volatility(days)


def calculate_sharpe_ratio(portfolio: List[Dict]) -> float:
    """Geriye uyumluluk için wrapper"""
    metrics = PortfolioMetrics(portfolio)
    return metrics.calculate_sharpe_ratio()